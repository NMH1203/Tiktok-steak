# TikTok Streak Auto-Messenger (Android + Terminal Menu)

Công cụ cá nhân chạy trên **máy server phụ** (Windows/Linux) để điều khiển **điện thoại Android** qua ADB (`uiautomator2`), tự động nhắn tin giữ chuỗi trên ứng dụng TikTok hằng ngày và quản lý hoàn toàn bằng menu **phím mũi tên (`↑`/`↓`) + `Enter`** trên Terminal.

---

## Tính năng chính

1. **Quét danh sách hội thoại từ TikTok Inbox:** Tự động mở TikTok -> tab *Hộp thư (Inbox)* -> cuộn danh sách để nhận diện tên hiển thị, tin nhắn gần nhất và badge chuỗi `🔥` (tự lọc bỏ các dòng thông báo hệ thống).
2. **Chọn người giữ chuỗi bằng `↑`/`↓` + `Enter`:** Bấm `Enter` vào tên từng người để bật/tắt `[✓]` / `[ ]` ngay tại chỗ, hoặc thêm tên thủ công.
3. **Kho câu nhắn random tiếng Việt:** Thêm, sửa, bật/tắt, xóa các mẫu câu tiếng Việt có dấu + emoji; hỗ trợ biến `{name}` để tự chèn tên người nhận và tránh lặp lại câu vừa gửi.
4. **Tự bật & mở khóa màn hình + tự khóa lại:**
   - Hỗ trợ tự đánh thức màn hình khi tắt, mở khóa kiểu **Vuốt (Swipe / None)** hoặc tự nhập **Mã PIN / Mật khẩu** do bạn cấu hình sẵn trong menu.
   - Tùy chọn tự tắt/khóa màn hình lại sau khi hoàn tất phiên gửi.
   - *(Lưu ý: Android không hỗ trợ mở khóa từ ADB bằng Hình vẽ Pattern hoặc Sinh trắc học; với máy phụ nên dùng kiểu Vuốt hoặc Mã PIN).*
5. **Tự động đóng thông báo/popup chen ngang:** Tự nhận diện và bấm tắt các hộp thoại gợi ý (nhập số điện thoại, đồng bộ danh bạ, bật thông báo, cập nhật app, quảng cáo...) để tiếp tục luồng gửi tin.
6. **Cơ chế an toàn tài khoản:**
   - Tùy chọn giờ chạy hằng ngày kèm độ lệch ngẫu nhiên (`jitter_minutes`) và khoảng nghỉ ngẫu nhiên giữa mỗi người.
   - Chế độ **Dry-run** (mở chat kiểm tra giao diện nhưng không bấm gửi) để test an toàn.
   - **Dừng khẩn cấp ngay lập tức** nếu gặp màn hình CAPTCHA/xác minh bảo mật hoặc màn hình yêu cầu đăng nhập lại/OTP.
7. **Chế độ chạy ngầm (`--daemon`):** Chạy 24/7 không cần mở giao diện menu trên máy server phụ.

---

## Yêu cầu & Cài đặt

### 1. Chuẩn bị trên điện thoại Android
- Bật **Tùy chọn nhà phát triển (Developer Options)** -> bật **Gỡ lỗi USB (USB Debugging)** (hoặc **Wireless Debugging** nếu kết nối qua Wi-Fi cùng mạng LAN).
- Đăng nhập sẵn tài khoản TikTok trên máy.
- Đặt khóa màn hình dạng **Không khóa / Vuốt**, hoặc **Mã PIN / Mật khẩu** (nếu muốn dùng tính năng tự nhập PIN mở khóa).

### 2. Cài đặt trên máy server phụ

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

> **Lưu ý về `adb`:** Thư viện `adbutils` đã tích hợp sẵn file thực thi `adb` bên trong `.venv`, nên bạn có thể cắm USB hoặc nối Wi-Fi ADB trực tiếp mà không cần cài thêm Android Studio.

---

## Hướng dẫn sử dụng

### Mở Menu Terminal (`↑` / `↓` + `Enter`)
```powershell
# Windows
.\.venv\Scripts\tiktok-streak.exe

# Hoặc chạy qua module Python (Windows/Linux)
python -m tiktok_streak.main
```

Các mục chính trong menu:
1. **Quét danh sách người từ TikTok Inbox** — kết nối điện thoại và quét danh sách chat.
2. **Chọn người giữ chuỗi** — dùng `↑`/`↓` + `Enter` để tick chọn người cần nhắn hằng ngày.
3. **Viết & quản lý câu nhắn random** — soạn kho câu tiếng Việt/emoji, hỗ trợ `{name}`.
4. **Cài đặt giờ chạy & thiết bị ADB** — bật lịch tự động, chỉnh giờ chạy, độ lệch `± phút`, delay, Dry-run, **nhập Mã PIN mở khóa màn hình**, bật/tắt tự khóa lại sau khi chạy, test mở khóa ngay, nối Wi-Fi ADB (`ip:port`), và **Dump UI XML** để debug.
5. **Chạy thử ngay (Dry-run)** — kiểm tra luồng thao tác mà không bấm gửi thật.
6. **Chạy gửi thật ngay** — gửi ngay 1 lượt cho danh sách đã chọn (tự bỏ qua người đã gửi trong ngày).
7. **Xem nhật ký gần đây** — kiểm tra lịch sử gửi, popup đã tắt, hoặc lỗi.
8. **Bật chạy ngầm tự động (Daemon 24/7)** — treo máy chờ đến khung giờ hằng ngày.

### Chạy trực tiếp từ dòng lệnh (CLI)
```powershell
# Chạy ngầm 24/7 theo cấu hình đã lưu trong data/tiktok_streak.db
tiktok-streak --daemon

# Chạy thử 1 lượt ngay rồi thoát
tiktok-streak --run-now --dry-run

# Chạy gửi thật 1 lượt ngay rồi thoát
tiktok-streak --run-now
```

---

## Cấu trúc mã nguồn

```text
├── pyproject.toml
├── README.md
├── src/tiktok_streak/
│   ├── main.py         # Entrypoint CLI (Menu / --daemon / --run-now)
│   ├── menu.py         # Giao diện Menu Terminal điều khiển bằng ↑/↓ và Enter
│   ├── models.py       # Dataclass cấu hình, người nhận, mẫu câu, nhật ký
│   ├── storage.py      # Lưu trữ SQLite (data/tiktok_streak.db)
│   ├── adb_client.py   # Kết nối ADB/uiautomator2, mở/khóa màn hình, gõ tiếng Việt
│   ├── xml_parser.py   # Phân tích UI XML TikTok, nhận diện popup, CAPTCHA, đăng nhập
│   ├── tiktok_bot.py   # Điều phối quét Inbox, tắt popup, gửi tin nhắn giữ chuỗi
│   └── scheduler.py    # Bộ lập lịch hằng ngày kèm jitter ngẫu nhiên
└── tests/              # Unit test (pytest) với FakeDriver & XML mẫu
```

---

## Kiểm thử & Debug khi TikTok đổi giao diện

Chạy toàn bộ unit test:
```powershell
pytest -v
```

Nếu phiên bản TikTok trên máy bạn thay đổi bố cục khiến bot không tìm thấy danh sách hội thoại hoặc nút gửi:
1. Mở màn hình TikTok cần kiểm tra trên điện thoại.
2. Vào mục **4. Cài đặt giờ chạy & thiết bị ADB** -> chọn **🧪 Dump UI XML hiện tại từ TikTok (Debug)**.
3. File XML sẽ được lưu trong thư mục `debug_dumps/` để bạn kiểm tra lại `text` / `content-desc` / `bounds` và cập nhật trong `src/tiktok_streak/xml_parser.py`.
