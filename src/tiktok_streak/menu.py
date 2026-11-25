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
    connect_wifi_adb,
    find_adb_binary,
    list_adb_devices,
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
    def pause(self, message: str = "Nhấn Enter để tiếp tục...") -> None: ...


class QuestionaryBackend:
    """Interactive terminal backend using questionary (Up/Down + Enter)."""

    def select(self, message: str, choices: list[Choice], default: Any = None) -> Any:
        return questionary.select(
            message,
            choices=choices,
            default=default,
            style=MENU_STYLE,
            instruction="(Dùng ↑/↓ di chuyển, Enter để chọn)",
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

    def pause(self, message: str = "Nhấn Enter để tiếp tục...") -> None:
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
            dev_txt = ", ".join(f"{s}({st})" for s, st in devs) if devs else "Chưa cắm máy"
        else:
            dev_txt = "Chưa có adb"

        sched_txt = f"BẬT ({cfg.target_time} ±{cfg.jitter_minutes}p)" if cfg.enabled else "TẮT"
        self.console.print()
        self.console.rule("[bold cyan]TikTok Streak Auto (Android + Terminal)[/bold cyan]")
        self.console.print(
            f"  [bold]Thiết bị ADB:[/bold] {dev_txt}  |  "
            f"[bold]Đang chọn:[/bold] {selected_cnt}/{len(contacts)} người  |  "
            f"[bold]Câu nhắn bật:[/bold] {tpl_cnt}  |  "
            f"[bold]Lịch tự động:[/bold] {sched_txt}"
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
                "Chọn chức năng:",
                choices=[
                    Choice("1. Quét danh sách người từ TikTok Inbox", "scan"),
                    Choice(f"2. Chọn người giữ chuỗi (đang chọn: {selected_cnt})", "contacts"),
                    Choice(f"3. Viết & quản lý câu nhắn random ({tpl_cnt} câu đang bật)", "templates"),
                    Choice("4. Cài đặt giờ chạy & thiết bị ADB", "schedule"),
                    Choice("5. Chạy thử ngay (Dry-run - không bấm gửi)", "run_dry"),
                    Choice("6. Chạy gửi thật ngay", "run_live"),
                    Choice("7. Xem nhật ký gần đây", "logs"),
                    Choice("8. Bật chạy ngầm tự động (Daemon 24/7)", "daemon"),
                    Choice("0. Thoát", "exit"),
                ],
            )

            if action is None or action == "exit":
                self.console.print("[cyan]Tạm biệt![/cyan]")
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
        self.console.print("\n[yellow]Đang quét danh sách hội thoại trên TikTok...[/yellow]")
        try:
            contacts = self.bot.scan_inbox(
                max_scrolls=4, cb=lambda m: self.console.print(f"  {m}")
            )
            self.console.print(f"[green]Hoàn tất! Hiện có {len(contacts)} người trong danh sách.[/green]")
        except Exception as exc:
            self.console.print(f"[red]Lỗi khi quét TikTok: {exc}[/red]")
        self.prompts.pause()

    def _handle_contacts_menu(self) -> None:
        cursor_val: Any = None
        while True:
            contacts = self.storage.list_contacts()
            choices: list[Choice] = [
                Choice("⬅️  Quay lại menu chính", _MenuAction("back")),
                Choice("➕ Thêm tên người nhận thủ công", _MenuAction("add")),
                Choice("✅ Chọn tất cả", _MenuAction("select_all")),
                Choice("⬜ Bỏ chọn tất cả", _MenuAction("deselect_all")),
                Choice("🗑️  Xóa một người khỏi danh sách", _MenuAction("delete")),
            ]
            for c in contacts:
                mark = "[✓]" if c.selected else "[ ]"
                streak = f" | {c.streak_info}" if c.streak_info else ""
                sent = f" | Gửi gần nhất: {c.last_sent_date}" if c.last_sent_date else ""
                choices.append(
                    Choice(
                        f"{mark} {c.display_name}{streak}{sent}",
                        _MenuAction("toggle", c.id),
                    )
                )

            selected = self.prompts.select(
                "Nhấn Enter vào tên để BẬT/TẮT giữ chuỗi:",
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
                name = self.prompts.text("Nhập đúng tên hiển thị trên TikTok Inbox:")
                if name and name.strip():
                    self.storage.add_manual_contact(name.strip(), selected=True)
                    self.console.print(f"[green]Đã thêm '{name.strip()}' (đã chọn).[/green]")
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
        choices = [Choice("⬅️  Hủy", None)] + [
            Choice(c.display_name, c.id) for c in contacts
        ]
        cid = self.prompts.select("Chọn người muốn xóa khỏi danh sách:", choices=choices)
        if cid is not None:
            self.storage.delete_contact(cid)

    def _handle_templates_menu(self) -> None:
        while True:
            templates = self.storage.list_templates()
            choices: list[Choice] = [
                Choice("⬅️  Quay lại menu chính", _MenuAction("back")),
                Choice("➕ Viết câu nhắn mới (hỗ trợ {name})", _MenuAction("add")),
                Choice("🎲 Xem thử 1 câu random", _MenuAction("preview")),
            ]
            for t in templates:
                status = "BẬT" if t.enabled else "TẮT"
                choices.append(
                    Choice(f"[{status}] {t.content}", _MenuAction("edit", t.id))
                )

            picked = self.prompts.select(
                "Chọn câu nhắn để sửa/bật-tắt/xóa, hoặc thêm câu mới:",
                choices=choices,
            )
            if picked is None or picked.key == "back":
                break
            if picked.key == "add":
                txt = self.prompts.text("Nhập câu nhắn (dùng {name} để chèn tên người nhận):")
                if txt and txt.strip():
                    self.storage.add_template(txt.strip(), enabled=True)
                    self.console.print("[green]Đã thêm câu nhắn mới.[/green]")
            elif picked.key == "preview":
                sample = self.storage.pick_random_template("Minh", avoid_repeat_last=False)
                self.console.print(
                    f"\n[cyan]Ví dụ random (tên 'Minh'):[/cyan] {sample or '(Chưa có câu nào đang bật)'}\n"
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
            f"Thao tác với câu: \"{tpl.content}\"",
            choices=[
                Choice("✏️  Sửa nội dung", "edit_text"),
                Choice("🔁 Đảo trạng thái BẬT / TẮT", "toggle"),
                Choice("🗑️  Xóa câu này", "delete"),
                Choice("⬅️  Quay lại", "back"),
            ],
        )
        if action == "edit_text":
            new_txt = self.prompts.text("Nội dung mới:", default=tpl.content)
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
                Choice("⬅️  Quay lại menu chính", "back"),
                Choice(
                    f"Lịch tự động hằng ngày: [{'BẬT' if cfg.enabled else 'TẮT'}] (Enter để bật/tắt)",
                    "toggle_enabled",
                ),
                Choice(f"Giờ chạy hằng ngày: [{cfg.target_time}]", "target_time"),
                Choice(f"Độ lệch ngẫu nhiên: [±{cfg.jitter_minutes} phút]", "jitter"),
                Choice(
                    f"Thời gian nghỉ giữa mỗi người: [{cfg.min_delay_sec} - {cfg.max_delay_sec} giây]",
                    "delays",
                ),
                Choice(
                    f"Chế độ Dry-run mặc định: [{'BẬT' if cfg.dry_run else 'TẮT'}]",
                    "toggle_dry",
                ),
                Choice(
                    f"Tránh lặp lại câu vừa gửi: [{'BẬT' if cfg.avoid_repeat_last else 'TẮT'}]",
                    "toggle_repeat",
                ),
                Choice(
                    f"Mã PIN / Mật khẩu mở khóa máy: [{'Đã đặt (••••)' if cfg.unlock_pin else 'Chưa đặt (chỉ vuốt mở)'}]",
                    "unlock_pin",
                ),
                Choice(
                    f"Tự tắt/khóa màn hình sau khi gửi xong: [{'BẬT' if cfg.auto_lock_after_run else 'TẮT'}]",
                    "toggle_auto_lock",
                ),
                Choice(
                    f"Serial / IP thiết bị: [{cfg.device_serial or 'Tự động máy đầu tiên'}]",
                    "serial",
                ),
                Choice("🔓 Kiểm tra bật & mở khóa màn hình ngay", "test_unlock"),
                Choice("🔌 Kết nối ADB qua Wi-Fi (nhập ip:port)", "wifi_adb"),
                Choice("🧪 Dump UI XML hiện tại từ TikTok (Debug)", "dump_xml"),
            ]
            choice = self.prompts.select("Cài đặt lịch chạy & thiết bị:", choices=choices)
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
                    "Nhập mã PIN/mật khẩu mở khóa điện thoại (để trống rồi Enter để xóa PIN):"
                )
                if pin is not None:
                    cfg.unlock_pin = pin.strip()
                    self.storage.save_schedule(cfg)
                    status_msg = "Đã lưu mã PIN mở khóa." if cfg.unlock_pin else "Đã xóa mã PIN (chỉ vuốt mở)."
                    self.console.print(f"[green]{status_msg}[/green]")
            elif choice == "test_unlock":
                try:
                    self.bot.test_unlock(cb=lambda m: self.console.print(f"  {m}"))
                    self.console.print("[green]Kiểm tra mở khóa thành công![/green]")
                except Exception as exc:
                    self.console.print(f"[red]Lỗi mở khóa: {exc}[/red]")
                self.prompts.pause()
            elif choice == "target_time":
                val = self.prompts.text("Nhập giờ chạy (HH:MM, ví dụ 20:00):", default=cfg.target_time)
                if val:
                    try:
                        parse_target_hm(val)
                        cfg.target_time = val.strip()
                        self.storage.save_schedule(cfg)
                    except ValueError as exc:
                        self.console.print(f"[red]{exc}[/red]")
                        self.prompts.pause()
            elif choice == "jitter":
                val = self.prompts.text("Nhập độ lệch ± phút (ví dụ 20):", default=str(cfg.jitter_minutes))
                if val and val.strip().isdigit():
                    cfg.jitter_minutes = int(val.strip())
                    self.storage.save_schedule(cfg)
            elif choice == "delays":
                d1 = self.prompts.text("Delay tối thiểu (giây):", default=str(cfg.min_delay_sec))
                d2 = self.prompts.text("Delay tối đa (giây):", default=str(cfg.max_delay_sec))
                if d1 and d2 and d1.strip().isdigit() and d2.strip().isdigit():
                    cfg.min_delay_sec = max(1, int(d1.strip()))
                    cfg.max_delay_sec = max(cfg.min_delay_sec, int(d2.strip()))
                    self.storage.save_schedule(cfg)
            elif choice == "serial":
                val = self.prompts.text(
                    "Nhập serial hoặc IP:Port (để trống = tự chọn thiết bị đầu tiên):",
                    default=cfg.device_serial,
                )
                if val is not None:
                    cfg.device_serial = val.strip()
                    self.storage.save_schedule(cfg)
            elif choice == "wifi_adb":
                addr = self.prompts.text("Nhập IP:Port của điện thoại (vd 192.168.1.25:5555):")
                if addr and addr.strip():
                    try:
                        out = connect_wifi_adb(addr.strip())
                        self.console.print(f"[cyan]{out}[/cyan]")
                        cfg.device_serial = addr.strip()
                        self.storage.save_schedule(cfg)
                    except Exception as exc:
                        self.console.print(f"[red]Lỗi Wi-Fi ADB: {exc}[/red]")
                    self.prompts.pause()
            elif choice == "dump_xml":
                try:
                    path = self.bot.dump_debug_xml()
                    self.console.print(f"[green]Đã lưu UI XML tại: {path}[/green]")
                except Exception as exc:
                    self.console.print(f"[red]Lỗi dump XML: {exc}[/red]")
                self.prompts.pause()

    def _handle_run_batch(self, dry_run: bool) -> None:
        if not dry_run:
            selected = self.storage.list_contacts(selected_only=True)
            if not selected:
                self.console.print("[yellow]Chưa chọn người nhận nào.[/yellow]")
                self.prompts.pause()
                return
            if not self.prompts.confirm(
                f"Xác nhận GỬI THẬT tin nhắn giữ chuỗi cho {len(selected)} người?",
                default=False,
            ):
                return

        label = "CHẠY THỬ (DRY-RUN)" if dry_run else "GỬI THẬT"
        self.console.print(f"\n[bold cyan]=== Bắt đầu phiên {label} ===[/bold cyan]")
        try:
            self.bot.run_streak_batch(
                dry_run=dry_run,
                only_unsent_today=not dry_run,
                cb=lambda msg: self.console.print(f"  {msg}"),
            )
        except Exception as exc:
            self.console.print(f"[red]Lỗi: {exc}[/red]")
        self.prompts.pause()

    def _handle_view_logs(self) -> None:
        logs = self.storage.list_logs(limit=25)
        table = Table(title="Nhật ký 25 hoạt động gần nhất")
        table.add_column("Thời gian", style="dim")
        table.add_column("Người nhận", style="cyan")
        table.add_column("Trạng thái", style="bold")
        table.add_column("Nội dung / Ghi chú")

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
                "Lịch tự động đang TẮT. Bạn có muốn BẬT lịch tự động rồi chạy ngầm ngay không?",
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
            f"\n[green]Đang chạy ngầm 24/7. Lần chạy kế tiếp: {next_at}. Nhấn Ctrl+C để quay lại.[/green]"
        )
        try:
            asyncio.run(scheduler.run_forever(poll_seconds=15.0))
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Đã dừng chế độ chạy ngầm.[/yellow]")
