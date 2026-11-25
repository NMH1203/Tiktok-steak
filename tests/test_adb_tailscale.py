"""Unit tests for Tailscale peer parsing and remote ADB target normalization."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from rich.console import Console

from tiktok_streak import menu as menu_mod
from tiktok_streak.adb_client import (
    TailscalePeer,
    is_remote_adb_target,
    normalize_remote_adb_target,
    parse_tailscale_status_json,
)
from tiktok_streak.menu import SimpleTerminalMenu
from tiktok_streak.storage import Storage
from tests.test_bot_and_scheduler import FakeDriver
from tests.test_menu import ScriptedPromptBackend


def test_normalize_and_detect_remote_adb_targets() -> None:
    assert normalize_remote_adb_target("100.64.10.5") == "100.64.10.5:5555"
    assert normalize_remote_adb_target("100.64.10.5:41234") == "100.64.10.5:41234"
    assert normalize_remote_adb_target("pixel-6.tail123.ts.net") == "pixel-6.tail123.ts.net:5555"
    assert normalize_remote_adb_target("R58M1234ABC") == "R58M1234ABC"

    assert is_remote_adb_target("100.64.10.5") is True
    assert is_remote_adb_target("192.168.1.25:5555") is True
    assert is_remote_adb_target("R58M1234ABC") is False


def test_parse_tailscale_status_json_prioritizes_android_online_peers() -> None:
    sample = json.dumps(
        {
            "Peer": {
                "node1": {
                    "HostName": "home-linux",
                    "DNSName": "home-linux.tail123.ts.net.",
                    "TailscaleIPs": ["100.64.0.2", "fd7a:115c::2"],
                    "OS": "linux",
                    "Online": True,
                },
                "node2": {
                    "HostName": "pixel-6",
                    "DNSName": "pixel-6.tail123.ts.net.",
                    "TailscaleIPs": ["100.64.0.99", "fd7a:115c::99"],
                    "OS": "android",
                    "Online": True,
                },
                "node3": {
                    "HostName": "old-xiaomi",
                    "DNSName": "old-xiaomi.tail123.ts.net.",
                    "TailscaleIPs": ["100.64.0.88"],
                    "OS": "android",
                    "Online": False,
                },
            }
        }
    )

    peers = parse_tailscale_status_json(sample)
    assert [p.hostname for p in peers] == ["pixel-6", "old-xiaomi", "home-linux"]
    assert peers[0].ipv4 == "100.64.0.99"
    assert peers[0].dns_name == "pixel-6.tail123.ts.net"


def test_menu_tailscale_connect_saves_target(tmp_path: Path, monkeypatch) -> None:
    db = Storage(tmp_path / "ts.db")
    driver = FakeDriver()
    console = Console(file=StringIO(), force_terminal=False)

    monkeypatch.setattr(
        menu_mod,
        "list_tailscale_peers",
        lambda: [
            TailscalePeer(
                hostname="pixel-6",
                dns_name="pixel-6.tail123.ts.net",
                ipv4="100.64.0.99",
                os_name="android",
                online=True,
            )
        ],
    )
    connected_targets: list[str] = []
    monkeypatch.setattr(
        menu_mod,
        "connect_remote_adb",
        lambda addr: connected_targets.append(addr) or f"connected to {addr}",
    )

    prompts = ScriptedPromptBackend(
        actions=["schedule", "tailscale_adb", "100.64.0.99", "back", "exit"],
        texts=["5555"],
    )

    try:
        menu = SimpleTerminalMenu(storage=db, driver=driver, prompts=prompts, console=console)
        menu.run()
        assert connected_targets == ["100.64.0.99:5555"]
        assert db.get_schedule().device_serial == "100.64.0.99:5555"
    finally:
        db.close()
