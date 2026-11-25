"""High-level TikTok Inbox scanning and streak messaging automation."""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path
from typing import Callable

from tiktok_streak.adb_client import DeviceDriver
from tiktok_streak.models import Contact, ScannedRow, SendLog
from tiktok_streak.storage import Storage
from tiktok_streak.xml_parser import (
    detect_captcha_or_block,
    detect_login_required,
    find_chat_input_bounds,
    find_dismiss_popup_bounds,
    find_node_bounds_by_labels,
    parse_inbox_conversations,
)

INBOX_TAB_LABELS = ("Hộp thư", "Inbox")
SEND_BUTTON_LABELS = ("Gửi", "Send")


class CaptchaDetectedError(RuntimeError):
    """Raised immediately when TikTok presents CAPTCHA or account verification."""


class LoginRequiredError(RuntimeError):
    """Raised when TikTok requires manual account login or OTP verification."""


ProgressCallback = Callable[[str], None]


class TikTokStreakBot:
    """Automates scanning TikTok Inbox contacts and sending daily streak messages."""

    def __init__(self, storage: Storage, driver: DeviceDriver) -> None:
        self.storage = storage
        self.driver = driver

    def _emit(self, cb: ProgressCallback | None, msg: str) -> None:
        if cb:
            cb(msg)

    def _guard_screen(self, xml_text: str) -> None:
        matched = detect_captcha_or_block(xml_text)
        if matched:
            raise CaptchaDetectedError(
                f"Phát hiện màn hình xác minh/CAPTCHA ('{matched}'). Dừng tự động để bảo vệ tài khoản."
            )
        login_match = detect_login_required(xml_text)
        if login_match:
            raise LoginRequiredError(
                f"TikTok yêu cầu đăng nhập/OTP ('{login_match}'). Hãy đăng nhập lại trên điện thoại."
            )

    def _dump_and_clear_popups(
        self, cb: ProgressCallback | None = None, max_dismiss: int = 3
    ) -> str:
        """Dump UI XML, guard against CAPTCHA/login, and auto-dismiss blocking popups."""
        xml = self.driver.dump_xml()
        self._guard_screen(xml)

        for _ in range(max_dismiss):
            found = find_dismiss_popup_bounds(xml)
            if not found:
                break
            label, bounds = found
            self._emit(cb, f"Phát hiện thông báo/popup ('{label}'), đang tự động tắt...")
            self.storage.add_log("SYSTEM", "", "POPUP_DISMISSED", f"Đã tắt nút '{label}'")
            self.driver.tap_bounds(bounds)
            self.driver.sleep(1.0)
            xml = self.driver.dump_xml()
            self._guard_screen(xml)
        return xml

    def _navigate_to_inbox(self, cb: ProgressCallback | None = None) -> str:
        """Open TikTok, navigate to the Inbox tab, and return the Inbox XML."""
        cfg = self.storage.get_schedule()
        self._emit(cb, "Đang kết nối thiết bị Android...")
        serial = self.driver.connect(cfg.device_serial)
        self._emit(cb, f"Đã kết nối: {serial}. Đang bật & mở khóa màn hình...")
        self.driver.ensure_screen_unlocked(cfg.unlock_pin)
        self._emit(cb, "Đang mở ứng dụng TikTok...")
        self.driver.open_tiktok()

        xml = self._dump_and_clear_popups(cb)

        inbox_bounds = find_node_bounds_by_labels(xml, INBOX_TAB_LABELS)
        if not inbox_bounds:
            # Close potential unlabeled full-screen promo/overlay and retry once
            self.driver.press_back()
            xml = self._dump_and_clear_popups(cb)
            inbox_bounds = find_node_bounds_by_labels(xml, INBOX_TAB_LABELS)

        if inbox_bounds:
            self._emit(cb, "Đang chuyển sang tab Hộp thư (Inbox)...")
            self.driver.tap_bounds(inbox_bounds)
            self.driver.sleep(2.0)
            xml = self._dump_and_clear_popups(cb)
        return xml

    def scan_inbox(
        self, max_scrolls: int = 4, cb: ProgressCallback | None = None
    ) -> list[Contact]:
        """Scan visible and scrolled Inbox conversations and persist them."""
        xml = self._navigate_to_inbox(cb)
        collected: dict[str, ScannedRow] = {}

        for scroll_idx in range(max_scrolls + 1):
            rows = parse_inbox_conversations(xml)
            for row in rows:
                if row.display_name not in collected:
                    collected[row.display_name] = row
            self._emit(
                cb,
                f"Lần quét {scroll_idx + 1}/{max_scrolls + 1}: nhận diện {len(collected)} hội thoại.",
            )
            if scroll_idx < max_scrolls:
                self.driver.swipe_up()
                xml = self._dump_and_clear_popups(cb)

        saved = self.storage.upsert_scanned_contacts(list(collected.values()))
        self.storage.add_log(
            contact_name="SYSTEM",
            message="",
            status="SCAN",
            detail=f"Quét được {len(collected)} hội thoại từ TikTok Inbox.",
        )
        return saved

    def _find_and_open_chat(
        self,
        display_name: str,
        max_scrolls: int = 6,
        cb: ProgressCallback | None = None,
    ) -> bool:
        """Scroll through Inbox until `display_name` is found and tap to open it."""
        for scroll_idx in range(max_scrolls + 1):
            xml = self._dump_and_clear_popups(cb)
            for row in parse_inbox_conversations(xml):
                if row.display_name.lower() == display_name.lower() and row.bounds != (0, 0, 0, 0):
                    self.driver.tap_bounds(row.bounds)
                    self.driver.sleep(1.5)
                    return True
            if scroll_idx < max_scrolls:
                self.driver.swipe_up()
        return False

    def _send_to_opened_chat(
        self, message: str, dry_run: bool, cb: ProgressCallback | None = None
    ) -> None:
        """Type and send (or dry-run verify) a message inside the currently open chat."""
        xml = self._dump_and_clear_popups(cb)

        input_bounds = find_chat_input_bounds(xml)
        if not input_bounds:
            # Try pressing Back once in case an unlabeled sheet covered the chat screen
            self.driver.press_back()
            xml = self._dump_and_clear_popups(cb)
            input_bounds = find_chat_input_bounds(xml)
        if not input_bounds:
            raise RuntimeError("Không tìm thấy ô nhập tin nhắn (EditText) trong khung chat.")

        if dry_run:
            return

        self.driver.tap_bounds(input_bounds)
        self.driver.sleep(0.6)
        self.driver.input_text(message)
        self.driver.sleep(0.8)

        xml_after_type = self._dump_and_clear_popups(cb)
        send_bounds = find_node_bounds_by_labels(xml_after_type, SEND_BUTTON_LABELS)
        if not send_bounds:
            raise RuntimeError("Đã nhập tin nhắn nhưng không tìm thấy nút Gửi (Send).")

        self.driver.tap_bounds(send_bounds)
        self.driver.sleep(1.0)

    def run_streak_batch(
        self,
        *,
        dry_run: bool | None = None,
        only_unsent_today: bool = True,
        cb: ProgressCallback | None = None,
    ) -> list[SendLog]:
        """Run streak messaging for all selected contacts."""
        cfg = self.storage.get_schedule()
        effective_dry_run = cfg.dry_run if dry_run is None else dry_run
        today_str = datetime.now().strftime("%Y-%m-%d")

        contacts = self.storage.list_contacts(selected_only=True)
        if not contacts:
            self._emit(cb, "Chưa có người nhận nào được chọn.")
            return []

        results: list[SendLog] = []
        connected = False
        try:
            self._navigate_to_inbox(cb)
            connected = True

            for idx, contact in enumerate(contacts):
                if only_unsent_today and not effective_dry_run and contact.last_sent_date == today_str:
                    log = self.storage.add_log(
                        contact.display_name, "", "SKIPPED", "Đã gửi hôm nay rồi."
                    )
                    results.append(log)
                    self._emit(cb, f"Bỏ qua {contact.display_name} (đã giữ chuỗi hôm nay).")
                    continue

                msg = self.storage.pick_random_template(
                    contact.display_name, avoid_repeat_last=cfg.avoid_repeat_last
                )
                if not msg:
                    log = self.storage.add_log(
                        contact.display_name, "", "ERROR", "Không có câu nhắn nào đang bật."
                    )
                    results.append(log)
                    self._emit(cb, "Dừng: không có mẫu câu nhắn nào đang bật.")
                    break

                self._emit(cb, f"[{idx + 1}/{len(contacts)}] Đang mở chat với {contact.display_name}...")
                try:
                    # Reset back to top of Inbox if not the first item
                    if idx > 0:
                        inbox_bounds = find_node_bounds_by_labels(
                            self._dump_and_clear_popups(cb), INBOX_TAB_LABELS
                        )
                        if inbox_bounds:
                            self.driver.tap_bounds(inbox_bounds)
                            self.driver.sleep(1.2)

                    if not self._find_and_open_chat(contact.display_name, cb=cb):
                        log = self.storage.add_log(
                            contact.display_name,
                            msg,
                            "ERROR",
                            "Không tìm thấy cuộc trò chuyện trong Hộp thư.",
                        )
                        results.append(log)
                        self._emit(cb, f"Lỗi: Không thấy {contact.display_name} trong Hộp thư.")
                        continue

                    self._send_to_opened_chat(msg, dry_run=effective_dry_run, cb=cb)

                    if effective_dry_run:
                        log = self.storage.add_log(
                            contact.display_name,
                            msg,
                            "DRY_RUN",
                            "Chạy thử: đã kiểm tra ô chat, chưa bấm gửi.",
                        )
                        self._emit(cb, f"[DRY-RUN] {contact.display_name} <- \"{msg}\"")
                    else:
                        self.storage.mark_contact_sent(contact.display_name, today_str)
                        log = self.storage.add_log(
                            contact.display_name, msg, "SUCCESS", "Đã gửi thành công."
                        )
                        self._emit(cb, f"[OK] {contact.display_name} <- \"{msg}\"")
                    results.append(log)

                except (CaptchaDetectedError, LoginRequiredError):
                    raise
                except Exception as exc:
                    log = self.storage.add_log(
                        contact.display_name, msg, "ERROR", str(exc)
                    )
                    results.append(log)
                    self._emit(cb, f"[LỖI] {contact.display_name}: {exc}")
                finally:
                    # Return to Inbox list before next contact
                    self.driver.press_back()

                if idx < len(contacts) - 1:
                    delay = random.uniform(cfg.min_delay_sec, cfg.max_delay_sec)
                    self._emit(cb, f"Chờ {delay:.1f}s trước người tiếp theo...")
                    self.driver.sleep(delay)

        except CaptchaDetectedError as exc:
            log = self.storage.add_log("SYSTEM", "", "CAPTCHA_STOP", str(exc))
            results.append(log)
            self._emit(cb, f"DỪNG KHẨN CẤP: {exc}")
        except LoginRequiredError as exc:
            log = self.storage.add_log("SYSTEM", "", "LOGIN_REQUIRED", str(exc))
            results.append(log)
            self._emit(cb, f"DỪNG: {exc}")
        finally:
            if connected and cfg.auto_lock_after_run:
                try:
                    self._emit(cb, "Đang tắt & khóa lại màn hình điện thoại...")
                    self.driver.lock_screen()
                except Exception:
                    pass

        return results

    def test_unlock(self, cb: ProgressCallback | None = None) -> str:
        """Connect to device and test waking/unlocking the screen without opening TikTok."""
        cfg = self.storage.get_schedule()
        self._emit(cb, "Đang kết nối thiết bị Android...")
        serial = self.driver.connect(cfg.device_serial)
        self._emit(cb, f"Đã kết nối {serial}. Thử bật & mở khóa màn hình...")
        self.driver.ensure_screen_unlocked(cfg.unlock_pin)
        self._emit(cb, "Màn hình đã mở khóa thành công!")
        return serial

    def dump_debug_xml(self, output_dir: str | Path = "debug_dumps") -> Path:
        """Connect to device and save raw UI XML snapshot for selector inspection."""
        cfg = self.storage.get_schedule()
        self.driver.connect(cfg.device_serial)
        xml = self.driver.dump_xml()
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = out_dir / f"tiktok_ui_{stamp}.xml"
        file_path.write_text(xml, encoding="utf-8")
        self.storage.add_log("SYSTEM", "", "DEBUG_DUMP", str(file_path))
        return file_path
