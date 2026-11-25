"""Data models for TikTok streak automation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Contact:
    """Represents a TikTok Inbox conversation discovered on the device."""

    display_name: str
    last_preview: str = ""
    streak_info: str = ""
    selected: bool = False
    last_sent_date: str | None = None
    updated_at: str = ""
    id: int | None = None


@dataclass(slots=True)
class MessageTemplate:
    """A randomizable message template supporting `{name}` placeholder."""

    content: str
    enabled: bool = True
    created_at: str = ""
    id: int | None = None


@dataclass(slots=True)
class ScheduleConfig:
    """Scheduling and safety settings for daily streak runs."""

    enabled: bool = False
    target_time: str = "20:00"
    jitter_minutes: int = 20
    min_delay_sec: int = 4
    max_delay_sec: int = 10
    dry_run: bool = True
    device_serial: str = ""
    avoid_repeat_last: bool = True
    unlock_pin: str = ""
    auto_lock_after_run: bool = True


@dataclass(slots=True)
class SendLog:
    """Audit record for each automated message attempt or scan event."""

    timestamp: str
    contact_name: str
    message: str
    status: str
    detail: str = ""
    id: int | None = None


@dataclass(slots=True)
class ScannedRow:
    """Raw conversation row parsed from TikTok Inbox XML hierarchy."""

    display_name: str
    last_preview: str = ""
    streak_info: str = ""
    bounds: tuple[int, int, int, int] = field(default=(0, 0, 0, 0))
    is_system: bool = False
