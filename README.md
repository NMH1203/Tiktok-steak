# TikTok Streak Auto-Messenger (Android + Terminal Menu)

A personal automation tool designed to run on a **secondary server/PC** (Windows/Linux) to control an **Android phone** over ADB (`uiautomator2`), keeping daily TikTok messaging streaks alive via a simple **Up/Down (`↑`/`↓`) + `Enter`** Terminal Menu.

---

## Key Features

1. **TikTok Inbox Contact Scanner:** Automatically launches TikTok, opens the *Inbox* tab, and scrolls to detect conversation display names, last message previews, and `🔥` streak badges (filtering out system notification rows).
2. **Simple Terminal Contact Selection (`↑`/`↓` + `Enter`):** Press `Enter` on any contact to toggle `[✓]` / `[ ]`, or add contacts manually.
3. **Randomizable Message Templates:** Create, edit, enable/disable, or delete message templates (Unicode & emoji supported), with `{name}` placeholder substitution and anti-repeat protection.
4. **Auto Wake, Unlock & Re-lock:**
   - Wakes the phone screen automatically when turned off, dismisses **Swipe** locks, or enters your configured **PIN / Password** to unlock.
   - Optionally turns off and locks the phone screen again after finishing the batch.
   - *(Note: Android does not allow ADB to unlock Pattern or Biometric-only locks; use Swipe/None or PIN/Password on your dedicated device).*
5. **Auto-Dismiss Blocking Popups:** Automatically detects and closes interrupting in-app prompts/dialogs (add phone number, sync contacts, enable notifications, app update prompts, promo overlays) so the task continues uninterrupted.
6. **Account Safety Guards:**
   - Daily schedule window with randomized jitter (`± minutes`) and randomized delays between contacts.
   - **Dry-run mode** to verify chat inputs without tapping Send.
   - **Emergency stop** on CAPTCHA/security verification or login/OTP screens.
7. **Headless Daemon Mode (`--daemon`):** Runs 24/7 unattended on your secondary server.

---

## Requirements & Setup

### 1. Android Phone Preparation
- Enable **Developer Options** -> enable **USB Debugging** (or **Wireless Debugging** over local Wi-Fi).
- Sign in to your TikTok account on the phone.
- Set screen lock to **None / Swipe**, or **PIN / Password** (if using auto-PIN unlock).

### 2. Secondary Server Setup

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

> **Note on `adb`:** `adbutils` bundles the `adb` binary inside `.venv`, so USB, LAN Wi-Fi, and Tailscale ADB connections work out of the box without installing Android Studio.

### 3. Remote Connection over Tailscale (Optional)
If your secondary server and Android phone are on different networks:
1. Install **Tailscale** on both the server and the Android phone and sign in to the same tailnet.
2. Disable battery optimization for the Tailscale app on Android so the VPN stays active while the screen is off.
3. Plug the phone in via USB once -> open **4. Schedule, unlock PIN & ADB settings** -> **Enable ADB TCP/IP 5555 on USB device (for Tailscale)** (then unplug USB). *(Alternatively, enable Android Wireless Debugging and use its shown port).*
4. Choose **Connect via Tailscale (pick Android peer)** in Settings — the app automatically detects Android peers in your tailnet (`100.x.y.z:5555`) and recovers stale offline TCP connections before each run.

---

## Usage

### Launch the Interactive Terminal Menu (`↑` / `↓` + `Enter`)
```powershell
# Windows
.\.venv\Scripts\tiktok-streak.exe

# Or via Python module (Windows/Linux)
python -m tiktok_streak.main
```

Menu options:
1. **Scan contacts from TikTok Inbox** — connects to the Android phone and scans Inbox conversations.
2. **Select streak contacts** — use `↑`/`↓` + `Enter` to toggle daily recipients.
3. **Write & manage random messages** — manage randomizable templates supporting `{name}`.
4. **Schedule, unlock PIN & ADB settings** — configure daily run time, jitter, delays, Dry-run, **Screen unlock PIN/password**, auto-lock after run, test screen unlock, Wi-Fi ADB (`ip:port`), and **Dump UI XML** for debugging.
5. **Run Dry-run now** — test opening chats without sending messages.
6. **Send streak messages now** — execute one batch immediately (skips contacts already sent today).
7. **View recent logs** — inspect sent messages, dismissed popups, and errors.
8. **Start 24/7 background daemon** — keep running until the scheduled daily window.

### Direct CLI Commands
```powershell
# Run headless 24/7 daemon using saved configuration in data/tiktok_streak.db
tiktok-streak --daemon

# Run a single Dry-run batch and exit
tiktok-streak --run-now --dry-run

# Run a single live batch and exit
tiktok-streak --run-now
```

---

## Project Structure

```text
├── pyproject.toml
├── README.md
├── src/tiktok_streak/
│   ├── main.py         # CLI entrypoint (Menu / --daemon / --run-now)
│   ├── menu.py         # Up/Down + Enter terminal menu
│   ├── models.py       # Dataclasses for contacts, templates, schedule, logs
│   ├── storage.py      # SQLite persistence (data/tiktok_streak.db)
│   ├── adb_client.py   # ADB/uiautomator2 wrapper, auto-unlock/lock, Unicode input
│   ├── xml_parser.py   # TikTok UI XML parser, popup/CAPTCHA/login detection
│   ├── tiktok_bot.py   # Inbox scanning, popup dismissal, streak messaging orchestration
│   └── scheduler.py    # Daily scheduler with randomized jitter
└── tests/              # pytest unit tests with FakeDriver & sample XMLs
```

---

## Testing & UI Debugging

Run all unit tests:
```powershell
pytest -v
```

If a TikTok app update changes Inbox/Chat layouts:
1. Open the target TikTok screen on the phone.
2. Go to **4. Schedule, unlock PIN & ADB settings** -> **Dump current TikTok UI XML (Debug)**.
3. Inspect the saved XML file under `debug_dumps/` and adjust selectors in `src/tiktok_streak/xml_parser.py`.
