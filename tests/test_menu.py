"""Unit tests for the simple Up/Down + Enter terminal menu."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

from questionary import Choice
from rich.console import Console

from tiktok_streak.menu import SimpleTerminalMenu
from tiktok_streak.storage import Storage
from tests.test_bot_and_scheduler import FakeDriver


class ScriptedPromptBackend:
    """Replays scripted menu selections and text inputs for deterministic testing."""

    def __init__(self, actions: list[Any], texts: list[str | None] | None = None) -> None:
        self._actions = list(actions)
        self._texts = list(texts or [])

    def select(self, message: str, choices: list[Choice], default: Any = None) -> Any:
        if not self._actions:
            return None
        target = self._actions.pop(0)
        # Prefer exact match on Choice.value before falling back to Choice.title substring
        for ch in choices:
            if ch.value == target:
                return ch.value
        for ch in choices:
            if isinstance(target, str) and isinstance(ch.title, str) and target in ch.title:
                return ch.value
        return target

    def text(self, message: str, default: str = "") -> str | None:
        if not self._texts:
            return default
        return self._texts.pop(0)

    def password(self, message: str) -> str | None:
        if not self._texts:
            return ""
        return self._texts.pop(0)

    def confirm(self, message: str, default: bool = False) -> bool:
        return True

    def pause(self, message: str = "Press Enter to continue...") -> None:
        pass


def test_simple_menu_scan_toggle_add_template_and_dry_run(tmp_path: Path) -> None:
    db = Storage(tmp_path / "menu.db")
    driver = FakeDriver()
    console = Console(file=StringIO(), force_terminal=False)

    # Scripted flow:
    # 1. Main -> "scan"
    # 2. Main -> "contacts" -> toggle "Linh Chi" -> "back"
    # 3. Main -> "templates" -> "add" ("Good evening {name}!") -> "back"
    # 4. Main -> "schedule" -> set "unlock_pin" ("2580") -> "test_unlock" -> "back"
    # 5. Main -> "run_dry"
    # 6. Main -> "exit"
    prompts = ScriptedPromptBackend(
        actions=[
            "scan",
            "contacts",
            "Linh Chi",
            "<- Back to main menu",
            "templates",
            "+ Add new message template",
            "<- Back to main menu",
            "schedule",
            "unlock_pin",
            "test_unlock",
            "back",
            "run_dry",
            "exit",
        ],
        texts=["Good evening {name}!", "2580"],
    )

    try:
        menu = SimpleTerminalMenu(storage=db, driver=driver, prompts=prompts, console=console)
        menu.run()

        contacts = {c.display_name: c for c in db.list_contacts()}
        assert "Linh Chi" in contacts
        assert contacts["Linh Chi"].selected is True
        assert contacts["Tuấn Anh"].selected is False

        templates = [t.content for t in db.list_templates()]
        assert "Good evening {name}!" in templates

        assert db.get_schedule().unlock_pin == "2580"
        assert "2580" in driver.unlock_pins_seen

        logs = db.list_logs()
        assert any(l.contact_name == "Linh Chi" and l.status == "DRY_RUN" for l in logs)
    finally:
        db.close()
