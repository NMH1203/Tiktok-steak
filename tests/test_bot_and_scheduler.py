"""Unit tests for TikTokStreakBot and StreakScheduler using a fake Android driver."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tiktok_streak.adb_client import parse_lock_state
from tiktok_streak.models import ScheduleConfig
from tiktok_streak.scheduler import StreakScheduler, compute_next_run
from tiktok_streak.storage import Storage
from tiktok_streak.tiktok_bot import TikTokStreakBot
from tests.test_xml_parser import SAMPLE_CHAT_XML, SAMPLE_INBOX_XML


class FakeDriver:
    """In-memory mock implementation of DeviceDriver."""

    def __init__(self, captcha_in_chat: bool = False) -> None:
        self.screen = "inbox"
        self.captcha_in_chat = captcha_in_chat
        self.typed_messages: list[str] = []
        self.taps: list[tuple[int, int]] = []
        self.back_presses = 0
        self.unlock_pins_seen: list[str] = []
        self.lock_calls = 0

    def connect(self, serial: str = "") -> str:
        return serial or "FAKE-DEVICE-01"

    def ensure_screen_unlocked(self, pin: str = "") -> None:
        self.unlock_pins_seen.append(pin)

    def lock_screen(self) -> None:
        self.lock_calls += 1

    def open_tiktok(self) -> str:
        self.screen = "inbox"
        return "com.ss.android.ugc.trill"

    def dump_xml(self) -> str:
        if self.screen == "chat":
            if self.captcha_in_chat:
                return "<hierarchy><node text='Slide to verify' /></hierarchy>"
            return SAMPLE_CHAT_XML
        return SAMPLE_INBOX_XML

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        # Tapping Linh Chi or Tuan Anh row opens chat
        if self.screen == "inbox" and 450 <= y <= 840:
            self.screen = "chat"

    def tap_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        x1, y1, x2, y2 = bounds
        self.tap((x1 + x2) // 2, (y1 + y2) // 2)

    def swipe_up(self) -> None:
        pass

    def press_back(self) -> None:
        self.back_presses += 1
        self.screen = "inbox"

    def input_text(self, text: str) -> None:
        self.typed_messages.append(text)

    def sleep(self, seconds: float) -> None:
        pass


def test_bot_scan_and_dry_run_then_live_send(tmp_path: Path) -> None:
    db = Storage(tmp_path / "bot.db")
    driver = FakeDriver()
    bot = TikTokStreakBot(db, driver)
    try:
        contacts = bot.scan_inbox(max_scrolls=1)
        names = [c.display_name for c in contacts]
        assert "Linh Chi" in names
        assert "Tuấn Anh" in names
        assert "Hoạt động mới" not in names  # system row excluded

        for c in contacts:
            db.set_contact_selected(c.id, True)  # type: ignore[arg-type]

        # Dry run should not type messages
        dry_logs = bot.run_streak_batch(dry_run=True)
        assert len(dry_logs) == 2
        assert all(l.status == "DRY_RUN" for l in dry_logs)
        assert driver.typed_messages == []

        # Live run should type and mark sent
        live_logs = bot.run_streak_batch(dry_run=False)
        assert len(live_logs) == 2
        assert all(l.status == "SUCCESS" for l in live_logs)
        assert len(driver.typed_messages) == 2

        # Second live run same day skips already-sent contacts
        second_logs = bot.run_streak_batch(dry_run=False, only_unsent_today=True)
        assert all(l.status == "SKIPPED" for l in second_logs)
    finally:
        db.close()


def test_bot_stops_immediately_on_captcha(tmp_path: Path) -> None:
    db = Storage(tmp_path / "captcha.db")
    driver = FakeDriver(captcha_in_chat=True)
    bot = TikTokStreakBot(db, driver)
    try:
        db.add_manual_contact("Linh Chi", selected=True)
        logs = bot.run_streak_batch(dry_run=False)
        assert any(l.status == "CAPTCHA_STOP" for l in logs)
        assert driver.typed_messages == []
    finally:
        db.close()


def test_compute_next_run_and_scheduler_tick(tmp_path: Path) -> None:
    cfg = ScheduleConfig(enabled=True, target_time="20:00", jitter_minutes=0)
    morning = datetime(2026, 11, 25, 9, 0, 0)
    due = compute_next_run(cfg, now=morning)
    assert due == datetime(2026, 11, 25, 20, 0, 0)

    after_window = datetime(2026, 11, 25, 21, 0, 0)
    due_tomorrow = compute_next_run(cfg, now=after_window)
    assert due_tomorrow == datetime(2026, 11, 26, 20, 0, 0)

    db = Storage(tmp_path / "sched.db")
    driver = FakeDriver()
    bot = TikTokStreakBot(db, driver)
    try:
        db.save_schedule(ScheduleConfig(enabled=True, target_time="09:00", jitter_minutes=0, dry_run=True))
        db.add_manual_contact("Linh Chi", selected=True)
        sched = StreakScheduler(db, bot)
        assert sched.tick_sync(now=datetime(2026, 11, 25, 8, 59, 0)) is False
        assert sched.tick_sync(now=datetime(2026, 11, 25, 9, 0, 5)) is True
        # Already ran today -> should not trigger again at 09:05
        assert sched.tick_sync(now=datetime(2026, 11, 25, 9, 5, 0)) is False
    finally:
        db.close()


def test_parse_lock_state_and_auto_unlock_with_pin_and_relock(tmp_path: Path) -> None:
    assert parse_lock_state("mShowingLockscreen=true mDreamingLockscreen=false") is True
    assert parse_lock_state("isStatusBarKeyguard=true") is True
    assert parse_lock_state("mShowingLockscreen=false isStatusBarKeyguard=false") is False

    db = Storage(tmp_path / "unlock.db")
    driver = FakeDriver()
    bot = TikTokStreakBot(db, driver)
    try:
        db.save_schedule(
            ScheduleConfig(dry_run=True, unlock_pin="1234", auto_lock_after_run=True)
        )
        db.add_manual_contact("Linh Chi", selected=True)
        bot.run_streak_batch(dry_run=True)

        assert driver.unlock_pins_seen == ["1234"]
        assert driver.lock_calls == 1
    finally:
        db.close()


class PopupInterruptDriver(FakeDriver):
    """Simulates popups blocking Inbox and Chat until dismissed."""

    def __init__(self) -> None:
        super().__init__()
        self.inbox_popup_open = True
        self.chat_popup_open = True

    def dump_xml(self) -> str:
        if self.screen == "inbox" and self.inbox_popup_open:
            return """<hierarchy>
              <node class="android.widget.TextView" text="Thêm số điện thoại hoặc đồng bộ danh bạ" bounds="[100,500][900,600]" />
              <node class="android.widget.Button" text="Để sau" clickable="true" bounds="[200,900][600,1000]" />
            </hierarchy>"""
        if self.screen == "chat" and self.chat_popup_open:
            return """<hierarchy>
              <node class="android.widget.TextView" text="Bật thông báo tin nhắn" bounds="[100,500][900,600]" />
              <node class="android.widget.Button" text="Không phải bây giờ" clickable="true" bounds="[200,900][600,1000]" />
            </hierarchy>"""
        return super().dump_xml()

    def tap(self, x: int, y: int) -> None:
        if self.screen == "inbox" and self.inbox_popup_open and 900 <= y <= 1000:
            self.inbox_popup_open = False
            return
        if self.screen == "chat" and self.chat_popup_open and 900 <= y <= 1000:
            self.chat_popup_open = False
            return
        super().tap(x, y)


def test_bot_auto_dismisses_blocking_popups_and_continues(tmp_path: Path) -> None:
    db = Storage(tmp_path / "popups.db")
    driver = PopupInterruptDriver()
    bot = TikTokStreakBot(db, driver)
    try:
        db.add_manual_contact("Linh Chi", selected=True)
        logs = bot.run_streak_batch(dry_run=False)
        assert len(logs) == 1
        assert logs[0].status == "SUCCESS"
        assert len(driver.typed_messages) == 1

        all_logs = db.list_logs()
        dismissed = [l for l in all_logs if l.status == "POPUP_DISMISSED"]
        assert len(dismissed) == 2
    finally:
        db.close()
