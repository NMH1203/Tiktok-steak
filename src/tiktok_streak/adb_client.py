"""ADB & uiautomator2 driver wrapper for controlling the Android device."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Protocol

from tiktok_streak.xml_parser import bounds_center, find_node_bounds_by_labels

TIKTOK_PACKAGES = (
    "com.ss.android.ugc.trill",      # TikTok Asia / Vietnam
    "com.zhiliaoapp.musically",      # TikTok Global
)

PIN_CONFIRM_LABELS = ("OK", "Enter", "Xác nhận", "Done", "Xong")


def parse_lock_state(dumpsys_output: str) -> bool:
    """Determine from `dumpsys window` / `dumpsys activity` output if keyguard is showing."""
    if not dumpsys_output:
        return False
    lowered = dumpsys_output.lower()
    for marker in (
        "mdreaminglockscreen=true",
        "mshowinglockscreen=true",
        "isstatusbarkeyguard=true",
        "mkeyguardshowing=true",
    ):
        if marker in lowered:
            return True
    return False


class DeviceDriver(Protocol):
    """Abstract interface for Android UI automation (real device or test mock)."""

    def connect(self, serial: str = "") -> str: ...
    def ensure_screen_unlocked(self, pin: str = "") -> None: ...
    def lock_screen(self) -> None: ...
    def open_tiktok(self) -> str: ...
    def dump_xml(self) -> str: ...
    def tap(self, x: int, y: int) -> None: ...
    def tap_bounds(self, bounds: tuple[int, int, int, int]) -> None: ...
    def swipe_up(self) -> None: ...
    def press_back(self) -> None: ...
    def input_text(self, text: str) -> None: ...
    def sleep(self, seconds: float) -> None: ...


def find_adb_binary() -> str | None:
    """Locate `adb` executable in PATH or standard Android SDK locations."""
    found = shutil.which("adb")
    if found:
        return found

    candidates = [
        Path.cwd() / "platform-tools" / "adb.exe",
        Path.cwd() / "platform-tools" / "adb",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        Path.home() / "Android" / "Sdk" / "platform-tools" / "adb",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)

    try:
        import adbutils

        bundled = adbutils.adb_path()
        if bundled and Path(bundled).is_file():
            return bundled
    except Exception:
        pass
    return None


def _ensure_adb_in_path() -> str:
    adb = find_adb_binary()
    if not adb:
        raise RuntimeError(
            "`adb` executable not found. Install Android Platform Tools and add it to PATH "
            "or place `platform-tools/` in the project root."
        )
    adb_dir = str(Path(adb).parent)
    current_path = os.environ.get("PATH", "")
    if adb_dir not in current_path.split(os.pathsep):
        os.environ["PATH"] = adb_dir + os.pathsep + current_path
    return adb


def list_adb_devices() -> list[tuple[str, str]]:
    """Return list of `(serial, status)` from `adb devices`."""
    adb = find_adb_binary()
    if not adb:
        return []
    try:
        proc = subprocess.run(
            [adb, "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return []

    devices: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            devices.append((parts[0], parts[1]))
    return devices


def connect_wifi_adb(address: str) -> str:
    """Connect to an Android device over TCP/IP (`ip:port`)."""
    adb = _ensure_adb_in_path()
    proc = subprocess.run(
        [adb, "connect", address.strip()],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return (proc.stdout or proc.stderr).strip()


class UiautomatorDriver:
    """Concrete Android driver backed by uiautomator2."""

    def __init__(self) -> None:
        self._device = None
        self._serial = ""
        self._active_package = ""

    def connect(self, serial: str = "") -> str:
        """Connect to a specific serial/IP:port or the first online ADB device."""
        _ensure_adb_in_path()
        import uiautomator2 as u2

        target = serial.strip()
        if target and ":" in target:
            connect_wifi_adb(target)

        if target:
            self._device = u2.connect(target)
        else:
            devices = [s for s, st in list_adb_devices() if st == "device"]
            if not devices:
                raise RuntimeError(
                    "No Android device in `device` state found. "
                    "Enable USB Debugging (or Wireless ADB) and check `adb devices`."
                )
            target = devices[0]
            self._device = u2.connect(target)

        self._serial = target
        return target

    @property
    def device(self):
        if self._device is None:
            raise RuntimeError("Not connected to an Android device.")
        return self._device

    def is_screen_locked(self) -> bool:
        """Check whether the Android lockscreen / keyguard is currently active."""
        d = self.device
        win_res = d.shell("dumpsys window policy")
        win_out = win_res.output if hasattr(win_res, "output") else str(win_res)
        if parse_lock_state(win_out):
            return True
        win_full = d.shell("dumpsys window windows")
        full_out = win_full.output if hasattr(win_full, "output") else str(win_full)
        return parse_lock_state(full_out)

    def ensure_screen_unlocked(self, pin: str = "") -> None:
        """Wake screen and unlock swipe or user-configured PIN/password lock."""
        d = self.device
        if not d.info.get("screenOn", True):
            d.screen_on()
            time.sleep(0.8)

        if not self.is_screen_locked():
            return

        # Dismiss non-secure swipe lockscreen first
        d.shell("wm dismiss-keyguard")
        time.sleep(0.4)
        w, h = d.window_size()
        d.swipe(w // 2, int(h * 0.8), w // 2, int(h * 0.25), duration=0.25)
        time.sleep(0.8)

        if not self.is_screen_locked():
            return

        if not pin:
            raise RuntimeError(
                "Screen is locked with a PIN/Password. "
                "Set the unlock PIN in Settings (option 4) or switch the device lock to Swipe/None."
            )

        d.shell(["input", "text", pin])
        time.sleep(0.3)
        d.press("enter")
        time.sleep(1.0)

        if self.is_screen_locked():
            xml = self.dump_xml()
            ok_bounds = find_node_bounds_by_labels(xml, PIN_CONFIRM_LABELS)
            if ok_bounds:
                self.tap_bounds(ok_bounds)
                time.sleep(1.0)

        if self.is_screen_locked():
            raise RuntimeError(
                "Failed to unlock phone (incorrect PIN or device uses Pattern/Biometric lock)."
            )

    def lock_screen(self) -> None:
        """Turn off and lock the Android screen after finishing work."""
        d = self.device
        if d.info.get("screenOn", False):
            d.screen_off()

    def open_tiktok(self) -> str:
        """Launch the installed TikTok package and return its package name."""
        d = self.device
        installed = set(d.app_list())
        for pkg in TIKTOK_PACKAGES:
            if pkg in installed:
                d.app_start(pkg, stop=False)
                self._active_package = pkg
                time.sleep(3.0)
                return pkg
        raise RuntimeError(
            "TikTok app (`com.ss.android.ugc.trill` or `com.zhiliaoapp.musically`) not found on device."
        )

    def dump_xml(self) -> str:
        """Return the current Android UI hierarchy XML string."""
        return self.device.dump_hierarchy(compressed=False)

    def tap(self, x: int, y: int) -> None:
        """Tap screen coordinates."""
        self.device.click(x, y)

    def tap_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        """Tap the center of an Android UI bounding box."""
        cx, cy = bounds_center(bounds)
        self.tap(cx, cy)

    def swipe_up(self) -> None:
        """Scroll down the current list by swiping upward."""
        d = self.device
        w, h = d.window_size()
        d.swipe(w // 2, int(h * 0.75), w // 2, int(h * 0.28), duration=0.35)
        time.sleep(1.2)

    def press_back(self) -> None:
        """Press Android Back button."""
        self.device.press("back")
        time.sleep(1.0)

    def input_text(self, text: str) -> None:
        """Type UTF-8 Vietnamese/emoji text via uiautomator2 FastInputIME."""
        d = self.device
        try:
            d.set_fastinput_ime(True)
            d.send_keys(text, clear=False)
        finally:
            try:
                d.set_fastinput_ime(False)
            except Exception:
                pass

    def sleep(self, seconds: float) -> None:
        """Pause execution for the given duration."""
        time.sleep(seconds)
