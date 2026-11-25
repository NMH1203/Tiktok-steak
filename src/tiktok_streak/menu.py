"""Simple arrow-key (Up/Down + Enter) Terminal Menu for TikTok Streak Automation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import questionary
from questionary import Choice, Style
from rich.console import Console
from rich.table import Table

from tiktok_streak.adb_client import (
    DeviceDriver,
    UiautomatorDriver,
    connect_remote_adb,
    enable_tcpip_mode,
    find_adb_binary,
    list_adb_devices,
    list_tailscale_peers,
    normalize_remote_adb_target,
)
from tiktok_streak.scheduler import StreakScheduler, parse_target_hm
from tiktok_streak.storage import Storage
from tiktok_streak.tiktok_bot import TikTokStreakBot

MENU_STYLE = Style(
    [
        ("qmark", "fg:#00d7ff bold"),
        ("question", "bold"),
        ("answer", "fg:#00ff87 bold"),
        ("pointer", "fg:#00d7ff bold"),
        ("highlighted", "fg:#00d7ff bold"),
        ("selected", "fg:#00ff87"),
        ("instruction", "fg:#8a8a8a"),
    ]
)


class PromptBackend(Protocol):
    """Input/output abstraction for arrow-key selection and text input."""

    def select(self, message: str, choices: list[Choice], default: Any = None) -> Any: ...
    def text(self, message: str, default: str = "") -> str | None: ...
    def password(self, message: str) -> str | None: ...
    def confirm(self, message: str, default: bool = False) -> bool: ...
    def pause(self, message: str = "Press Enter to continue...") -> None: ...


class QuestionaryBackend:
    """Interactive terminal backend using questionary (Up/Down + Enter)."""

    def select(self, message: str, choices: list[Choice], default: Any = None) -> Any:
        return questionary.select(
            message,
            choices=choices,
            default=default,
            style=MENU_STYLE,
            instruction="(Use ↑/↓ to move, Enter to select)",
            use_indicator=True,
        ).ask()

    def text(self, message: str, default: str = "") -> str | None:
        return questionary.text(
            message,
            default=default,
            style=MENU_STYLE,
        ).ask()

    def password(self, message: str) -> str | None:
        return questionary.password(
            message,
            style=MENU_STYLE,
        ).ask()

    def confirm(self, message: str, default: bool = False) -> bool:
        ans = questionary.confirm(message, default=default, style=MENU_STYLE).ask()
        return bool(ans)

    def pause(self, message: str = "Press Enter to continue...") -> None:
        questionary.press_any_key_to_continue(message=message, style=MENU_STYLE).ask()


@dataclass(slots=True)
class _MenuAction:
    key: str
    payload: Any = None


class SimpleTerminalMenu:
    """Simple Up/Down + Enter terminal controller."""

    def __init__(
        self,
        storage: Storage,
        driver: DeviceDriver | None = None,
        prompts: PromptBackend | None = None,
        console: Console | None = None,
    ) -> None:
        self.storage = storage
        self.driver = driver or UiautomatorDriver()
        self.bot = TikTokStreakBot(self.storage, self.driver)
        self.prompts = prompts or QuestionaryBackend()
        self.console = console or Console()

    def _print_summary_header(self) -> None:
        contacts = self.storage.list_contacts()
        selected_cnt = sum(1 for c in contacts if c.selected)
        tpl_cnt = len(self.storage.list_templates(enabled_only=True))
        cfg = self.storage.get_schedule()

        adb_bin = find_adb_binary()
        if adb_bin:
            devs = list_adb_devices()
            dev_txt = ", ".join(f"{s}({st})" for s, st in devs) if devs else "No device connected"
        else:
            dev_txt = "adb not found"

        sched_txt = f"ON ({cfg.target_time} ±{cfg.jitter_minutes}m)" if cfg.enabled else "OFF"
        self.console.print()
        self.console.rule("[bold cyan]TikTok Streak Auto (Android + Terminal)[/bold cyan]")
        self.console.print(
            f"  [bold]ADB Device:[/bold] {dev_txt}  |  "
            f"[bold]Selected:[/bold] {selected_cnt}/{len(contacts)} contacts  |  "
            f"[bold]Active templates:[/bold] {tpl_cnt}  |  "
            f"[bold]Schedule:[/bold] {sched_txt}"
        )
        self.console.print()

    def run(self) -> None:
        """Run the interactive main menu loop until user exits."""
        while True:
            self._print_summary_header()
            contacts = self.storage.list_contacts()
            selected_cnt = sum(1 for c in contacts if c.selected)
            tpl_cnt = len(self.storage.list_templates(enabled_only=True))

            action = self.prompts.select(
                "Select an action:",
                choices=[
                    Choice("1. Scan contacts from TikTok Inbox", "scan"),
                    Choice(f"2. Select streak contacts (selected: {selected_cnt})", "contacts"),
                    Choice(f"3. Write & manage random messages ({tpl_cnt} active)", "templates"),
                    Choice("4. Schedule, unlock PIN & ADB settings", "schedule"),
                    Choice("5. Run Dry-run now (no actual send)", "run_dry"),
                    Choice("6. Send streak messages now", "run_live"),
                    Choice("7. View recent logs", "logs"),
                    Choice("8. Start 24/7 background daemon", "daemon"),
                    Choice("0. Exit", "exit"),
                ],
            )

            if action is None or action == "exit":
                self.console.print("[cyan]Goodbye![/cyan]")
                break

            handlers: dict[str, Callable[[], None]] = {
                "scan": self._handle_scan,
                "contacts": self._handle_contacts_menu,
                "templates": self._handle_templates_menu,
                "schedule": self._handle_schedule_menu,
                "run_dry": lambda: self._handle_run_batch(dry_run=True),
                "run_live": lambda: self._handle_run_batch(dry_run=False),
                "logs": self._handle_view_logs,
                "daemon": self._handle_daemon,
            }
            handler = handlers.get(action)
            if handler:
                handler()

    # --- Menu Handlers ---

    def _handle_scan(self) -> None:
        self.console.print("\n[yellow]Scanning conversations on TikTok...[/yellow]")
        try:
            contacts = self.bot.scan_inbox(
                max_scrolls=4, cb=lambda m: self.console.print(f"  {m}")
            )
            self.console.print(f"[green]Done! {len(contacts)} contacts saved in list.[/green]")
        except Exception as exc:
            self.console.print(f"[red]Scan error: {exc}[/red]")
        self.prompts.pause()

    def _handle_contacts_menu(self) -> None:
        cursor_val: Any = None
        while True:
            contacts = self.storage.list_contacts()
            choices: list[Choice] = [
                Choice("<- Back to main menu", _MenuAction("back")),
                Choice("+ Add contact manually", _MenuAction("add")),
                Choice("[✓] Select all", _MenuAction("select_all")),
                Choice("[ ] Deselect all", _MenuAction("deselect_all")),
                Choice("x Delete a contact", _MenuAction("delete")),
            ]
            for c in contacts:
                mark = "[✓]" if c.selected else "[ ]"
                streak = f" | {c.streak_info}" if c.streak_info else ""
                sent = f" | Last sent: {c.last_sent_date}" if c.last_sent_date else ""
                choices.append(
                    Choice(
                        f"{mark} {c.display_name}{streak}{sent}",
                        _MenuAction("toggle", c.id),
                    )
                )

            selected = self.prompts.select(
                "Press Enter on a contact to toggle ON/OFF:",
                choices=choices,
                default=cursor_val,
            )
            if selected is None or selected.key == "back":
                break
            if selected.key == "toggle":
                cid = selected.payload
                current = next((c for c in contacts if c.id == cid), None)
                if current:
                    self.storage.set_contact_selected(cid, not current.selected)
                    cursor_val = selected
            elif selected.key == "add":
                name = self.prompts.text("Enter exact display name shown in TikTok Inbox:")
                if name and name.strip():
                    self.storage.add_manual_contact(name.strip(), selected=True)
                    self.console.print(f"[green]Added '{name.strip()}' (selected).[/green]")
            elif selected.key == "select_all":
                self.storage.set_all_contacts_selected(True)
            elif selected.key == "deselect_all":
                self.storage.set_all_contacts_selected(False)
            elif selected.key == "delete":
                self._delete_contact_subflow()
                cursor_val = None

    def _delete_contact_subflow(self) -> None:
        contacts = self.storage.list_contacts()
        if not contacts:
            return
        choices = [Choice("<- Cancel", None)] + [
            Choice(c.display_name, c.id) for c in contacts
        ]
        cid = self.prompts.select("Select contact to remove:", choices=choices)
        if cid is not None:
            self.storage.delete_contact(cid)

    def _handle_templates_menu(self) -> None:
        while True:
            templates = self.storage.list_templates()
            choices: list[Choice] = [
                Choice("<- Back to main menu", _MenuAction("back")),
                Choice("+ Add new message template (supports {name})", _MenuAction("add")),
                Choice("? Preview a random message", _MenuAction("preview")),
            ]
            for t in templates:
                status = "ON" if t.enabled else "OFF"
                choices.append(
                    Choice(f"[{status}] {t.content}", _MenuAction("edit", t.id))
                )

            picked = self.prompts.select(
                "Select a template to edit/toggle/delete, or add a new one:",
                choices=choices,
            )
            if picked is None or picked.key == "back":
                break
            if picked.key == "add":
                txt = self.prompts.text("Enter message text (use {name} for recipient name):")
                if txt and txt.strip():
                    self.storage.add_template(txt.strip(), enabled=True)
                    self.console.print("[green]Added new template.[/green]")
            elif picked.key == "preview":
                sample = self.storage.pick_random_template("Alex", avoid_repeat_last=False)
                self.console.print(
                    f"\n[cyan]Random preview (name 'Alex'):[/cyan] {sample or '(No enabled templates)'}\n"
                )
                self.prompts.pause()
            elif picked.key == "edit":
                self._edit_single_template(picked.payload)

    def _edit_single_template(self, template_id: int) -> None:
        templates = {t.id: t for t in self.storage.list_templates()}
        tpl = templates.get(template_id)
        if not tpl:
            return
        action = self.prompts.select(
            f"Action for template: \"{tpl.content}\"",
            choices=[
                Choice("Edit content", "edit_text"),
                Choice("Toggle ON / OFF", "toggle"),
                Choice("Delete template", "delete"),
                Choice("<- Back", "back"),
            ],
        )
        if action == "edit_text":
            new_txt = self.prompts.text("New content:", default=tpl.content)
            if new_txt and new_txt.strip():
                self.storage.update_template(template_id, content=new_txt.strip())
        elif action == "toggle":
            self.storage.update_template(template_id, enabled=not tpl.enabled)
        elif action == "delete":
            self.storage.delete_template(template_id)

    def _handle_schedule_menu(self) -> None:
        while True:
            cfg = self.storage.get_schedule()
            choices = [
                Choice("<- Back to main menu", "back"),
                Choice(
                    f"Daily auto-schedule: [{'ON' if cfg.enabled else 'OFF'}] (Enter to toggle)",
                    "toggle_enabled",
                ),
                Choice(f"Daily target time: [{cfg.target_time}]", "target_time"),
                Choice(f"Random jitter window: [±{cfg.jitter_minutes} min]", "jitter"),
                Choice(
                    f"Delay between contacts: [{cfg.min_delay_sec} - {cfg.max_delay_sec} sec]",
                    "delays",
                ),
                Choice(
                    f"Default Dry-run mode: [{'ON' if cfg.dry_run else 'OFF'}]",
                    "toggle_dry",
                ),
                Choice(
                    f"Avoid repeating last sent message: [{'ON' if cfg.avoid_repeat_last else 'OFF'}]",
                    "toggle_repeat",
                ),
                Choice(
                    f"Screen unlock PIN / Password: [{'Set (••••)' if cfg.unlock_pin else 'Not set (swipe only)'}]",
                    "unlock_pin",
                ),
                Choice(
                    f"Auto-lock screen after run: [{'ON' if cfg.auto_lock_after_run else 'OFF'}]",
                    "toggle_auto_lock",
                ),
                Choice(
                    f"Device serial / Tailscale / Wi-Fi IP: [{cfg.device_serial or 'Auto-select first device'}]",
                    "serial",
                ),
                Choice("Test wake & unlock screen now", "test_unlock"),
                Choice("Connect via Tailscale (pick Android peer)", "tailscale_adb"),
                Choice("Connect Remote / Wi-Fi ADB (IP:Port)", "wifi_adb"),
                Choice("Enable ADB TCP/IP 5555 on USB device (for Tailscale)", "enable_tcpip"),
                Choice("Dump current TikTok UI XML (Debug)", "dump_xml"),
            ]
            choice = self.prompts.select("Schedule, Unlock & ADB Settings:", choices=choices)
            if choice is None or choice == "back":
                break
            if choice == "toggle_enabled":
                cfg.enabled = not cfg.enabled
                self.storage.save_schedule(cfg)
            elif choice == "toggle_dry":
                cfg.dry_run = not cfg.dry_run
                self.storage.save_schedule(cfg)
            elif choice == "toggle_repeat":
                cfg.avoid_repeat_last = not cfg.avoid_repeat_last
                self.storage.save_schedule(cfg)
            elif choice == "toggle_auto_lock":
                cfg.auto_lock_after_run = not cfg.auto_lock_after_run
                self.storage.save_schedule(cfg)
            elif choice == "unlock_pin":
                pin = self.prompts.password(
                    "Enter phone lockscreen PIN/password (leave empty and press Enter to clear):"
                )
                if pin is not None:
                    cfg.unlock_pin = pin.strip()
                    self.storage.save_schedule(cfg)
                    status_msg = "Unlock PIN saved." if cfg.unlock_pin else "Unlock PIN cleared (swipe only)."
                    self.console.print(f"[green]{status_msg}[/green]")
            elif choice == "test_unlock":
                try:
                    self.bot.test_unlock(cb=lambda m: self.console.print(f"  {m}"))
                    self.console.print("[green]Unlock test succeeded![/green]")
                except Exception as exc:
                    self.console.print(f"[red]Unlock error: {exc}[/red]")
                self.prompts.pause()
            elif choice == "target_time":
                val = self.prompts.text("Enter target time (HH:MM, e.g. 20:00):", default=cfg.target_time)
                if val:
                    try:
                        parse_target_hm(val)
                        cfg.target_time = val.strip()
                        self.storage.save_schedule(cfg)
                    except ValueError as exc:
                        self.console.print(f"[red]{exc}[/red]")
                        self.prompts.pause()
            elif choice == "jitter":
                val = self.prompts.text("Enter random jitter ± minutes (e.g. 20):", default=str(cfg.jitter_minutes))
                if val and val.strip().isdigit():
                    cfg.jitter_minutes = int(val.strip())
                    self.storage.save_schedule(cfg)
            elif choice == "delays":
                d1 = self.prompts.text("Minimum delay (seconds):", default=str(cfg.min_delay_sec))
                d2 = self.prompts.text("Maximum delay (seconds):", default=str(cfg.max_delay_sec))
                if d1 and d2 and d1.strip().isdigit() and d2.strip().isdigit():
                    cfg.min_delay_sec = max(1, int(d1.strip()))
                    cfg.max_delay_sec = max(cfg.min_delay_sec, int(d2.strip()))
                    self.storage.save_schedule(cfg)
            elif choice == "serial":
                val = self.prompts.text(
                    "Enter ADB serial, Tailscale IP/MagicDNS, or IP:Port (blank = first device):",
                    default=cfg.device_serial,
                )
                if val is not None:
                    cfg.device_serial = normalize_remote_adb_target(val.strip()) if val.strip() else ""
                    self.storage.save_schedule(cfg)
            elif choice == "tailscale_adb":
                self._connect_tailscale_flow(cfg)
            elif choice == "wifi_adb":
                addr = self.prompts.text("Enter phone IP or IP:Port (default port 5555, e.g. 100.64.0.10 or 192.168.1.25:5555):")
                if addr and addr.strip():
                    try:
                        normalized = normalize_remote_adb_target(addr.strip())
                        out = connect_remote_adb(normalized)
                        self.console.print(f"[cyan]{out}[/cyan]")
                        cfg.device_serial = normalized
                        self.storage.save_schedule(cfg)
                    except Exception as exc:
                        self.console.print(f"[red]Remote ADB error: {exc}[/red]")
                    self.prompts.pause()
            elif choice == "enable_tcpip":
                try:
                    out = enable_tcpip_mode(port=5555)
                    self.console.print(f"[green]{out or 'ADB TCP/IP 5555 enabled.'}[/green]")
                    self.console.print("[dim]You can now unplug USB and connect via Tailscale IP:5555.[/dim]")
                except Exception as exc:
                    self.console.print(f"[red]TCP/IP enable error: {exc}[/red]")
                self.prompts.pause()
            elif choice == "dump_xml":
                try:
                    path = self.bot.dump_debug_xml()
                    self.console.print(f"[green]Saved UI XML snapshot to: {path}[/green]")
                except Exception as exc:
                    self.console.print(f"[red]XML dump error: {exc}[/red]")
                self.prompts.pause()

    def _connect_tailscale_flow(self, cfg: Any) -> None:
        """Discover Tailscale peers, pick an Android phone, and connect ADB over Tailscale."""
        peers = list_tailscale_peers()
        choices: list[Choice] = [Choice("<- Cancel", None)]
        for p in peers:
            status_lbl = "Online" if p.online else "Offline"
            choices.append(
                Choice(
                    f"{p.hostname} [{p.os_name} | {status_lbl} | {p.ipv4}]",
                    p.ipv4,
                )
            )
        choices.append(Choice("+ Enter Tailscale IP / MagicDNS manually", "__manual__"))

        picked = self.prompts.select("Select Tailscale peer for ADB:", choices=choices)
        if not picked:
            return

        host = picked
        if picked == "__manual__":
            entered = self.prompts.text("Enter Tailscale IP or MagicDNS (e.g. 100.80.1.5 or phone.tail123.ts.net):")
            if not entered or not entered.strip():
                return
            host = entered.strip()

        port_str = self.prompts.text("ADB port (default 5555, or Android Wireless Debugging port):", default="5555")
        port = port_str.strip() if port_str and port_str.strip() else "5555"
        target = host if ":" in host else f"{host}:{port}"

        try:
            out = connect_remote_adb(target)
            self.console.print(f"[cyan]{out}[/cyan]")
            cfg.device_serial = target
            self.storage.save_schedule(cfg)
            self.console.print(f"[green]Saved device target: {target}[/green]")
        except Exception as exc:
            self.console.print(f"[red]Tailscale ADB error: {exc}[/red]")
        self.prompts.pause()

    def _handle_run_batch(self, dry_run: bool) -> None:
        if not dry_run:
            selected = self.storage.list_contacts(selected_only=True)
            if not selected:
                self.console.print("[yellow]No contacts selected.[/yellow]")
                self.prompts.pause()
                return
            if not self.prompts.confirm(
                f"Confirm sending LIVE streak messages to {len(selected)} contacts?",
                default=False,
            ):
                return

        label = "DRY-RUN" if dry_run else "LIVE SEND"
        self.console.print(f"\n[bold cyan]=== Starting {label} batch ===[/bold cyan]")
        try:
            self.bot.run_streak_batch(
                dry_run=dry_run,
                only_unsent_today=not dry_run,
                cb=lambda msg: self.console.print(f"  {msg}"),
            )
        except Exception as exc:
            self.console.print(f"[red]Error: {exc}[/red]")
        self.prompts.pause()

    def _handle_view_logs(self) -> None:
        logs = self.storage.list_logs(limit=25)
        table = Table(title="Recent 25 Activity Logs")
        table.add_column("Timestamp", style="dim")
        table.add_column("Contact", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Message / Detail")

        for log in logs:
            detail = log.message if log.message else log.detail
            table.add_row(log.timestamp, log.contact_name, log.status, detail)

        self.console.print()
        self.console.print(table)
        self.console.print()
        self.prompts.pause()

    def _handle_daemon(self) -> None:
        cfg = self.storage.get_schedule()
        if not cfg.enabled:
            if self.prompts.confirm(
                "Daily auto-schedule is currently OFF. Enable it and start the 24/7 daemon now?",
                default=True,
            ):
                cfg.enabled = True
                self.storage.save_schedule(cfg)
            else:
                return

        scheduler = StreakScheduler(
            self.storage, self.bot, on_status=lambda m: self.console.print(f"  {m}")
        )
        next_at = scheduler.refresh_schedule()
        self.console.print(
            f"\n[green]Running 24/7 daemon. Next run: {next_at}. Press Ctrl+C to stop.[/green]"
        )
        try:
            asyncio.run(scheduler.run_forever(poll_seconds=15.0))
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Daemon stopped.[/yellow]")
