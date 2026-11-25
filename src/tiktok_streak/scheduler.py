"""Daily streak scheduler with randomized jitter window."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Callable

from tiktok_streak.models import ScheduleConfig
from tiktok_streak.storage import Storage
from tiktok_streak.tiktok_bot import TikTokStreakBot


def parse_target_hm(target_time: str) -> tuple[int, int]:
    """Parse `HH:MM` string into `(hour, minute)` with validation."""
    parts = target_time.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Giờ chạy không hợp lệ: '{target_time}' (cần định dạng HH:MM)")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Giờ chạy ngoài phạm vi 00:00-23:59: '{target_time}'")
    return hour, minute


def compute_next_run(
    cfg: ScheduleConfig,
    *,
    now: datetime | None = None,
    last_run_date: str | None = None,
) -> datetime:
    """Compute the next scheduled execution timestamp with random jitter."""
    ref = now or datetime.now()
    hour, minute = parse_target_hm(cfg.target_time)
    base_today = ref.replace(hour=hour, minute=minute, second=0, microsecond=0)
    offset = random.randint(-cfg.jitter_minutes, cfg.jitter_minutes) if cfg.jitter_minutes > 0 else 0
    candidate = base_today + timedelta(minutes=offset)

    today_str = ref.strftime("%Y-%m-%d")
    if last_run_date == today_str or candidate <= ref:
        tomorrow_base = base_today + timedelta(days=1)
        offset_tomorrow = (
            random.randint(-cfg.jitter_minutes, cfg.jitter_minutes)
            if cfg.jitter_minutes > 0
            else 0
        )
        candidate = tomorrow_base + timedelta(minutes=offset_tomorrow)
    return candidate


class StreakScheduler:
    """Manages periodic checks and triggers `TikTokStreakBot.run_streak_batch` once per day."""

    def __init__(
        self,
        storage: Storage,
        bot: TikTokStreakBot,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.storage = storage
        self.bot = bot
        self.on_status = on_status
        self.next_run_at: datetime | None = None
        self.last_run_date: str | None = None
        self._last_signature: tuple[bool, str, int] | None = None

    def refresh_schedule(self, now: datetime | None = None) -> datetime | None:
        """Recompute `next_run_at` when schedule config changes or after a run."""
        cfg = self.storage.get_schedule()
        if not cfg.enabled:
            self.next_run_at = None
            self._last_signature = None
            return None

        sig = (cfg.enabled, cfg.target_time, cfg.jitter_minutes)
        if self.next_run_at is None or sig != self._last_signature:
            self.next_run_at = compute_next_run(
                cfg, now=now, last_run_date=self.last_run_date
            )
            self._last_signature = sig
        return self.next_run_at

    def tick_sync(self, now: datetime | None = None) -> bool:
        """Check if scheduled run is due; execute synchronously and return True if triggered."""
        ref = now or datetime.now()
        due_at = self.refresh_schedule(now=ref)
        if due_at is None or ref < due_at:
            return False

        today_str = ref.strftime("%Y-%m-%d")
        self.last_run_date = today_str
        if self.on_status:
            self.on_status(f"Đến giờ chạy tự động ({ref.strftime('%H:%M:%S')})...")

        self.bot.run_streak_batch(cb=self.on_status)

        cfg = self.storage.get_schedule()
        if cfg.enabled:
            self.next_run_at = compute_next_run(
                cfg, now=datetime.now(), last_run_date=self.last_run_date
            )
        else:
            self.next_run_at = None
        return True

    async def run_forever(self, poll_seconds: float = 15.0) -> None:
        """Async daemon loop suitable for headless server execution."""
        while True:
            try:
                await asyncio.to_thread(self.tick_sync)
            except Exception as exc:
                if self.on_status:
                    self.on_status(f"Lỗi scheduler: {exc}")
            await asyncio.sleep(poll_seconds)
