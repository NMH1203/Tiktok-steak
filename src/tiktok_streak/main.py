"""CLI entry point supporting simple arrow-key menu and headless daemon mode."""

from __future__ import annotations

import argparse
import asyncio
import sys

from tiktok_streak.adb_client import UiautomatorDriver
from tiktok_streak.menu import SimpleTerminalMenu
from tiktok_streak.scheduler import StreakScheduler
from tiktok_streak.storage import Storage
from tiktok_streak.tiktok_bot import TikTokStreakBot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="tiktok-streak",
        description="Automate daily TikTok streak messages on Android via ADB + Terminal Menu.",
    )
    parser.add_argument(
        "--db",
        default="data/tiktok_streak.db",
        help="Path to SQLite configuration database (default: data/tiktok_streak.db)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run headless in background (for 24/7 secondary server).",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run a single streak batch immediately and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use with --run-now to test without actually tapping Send.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Application entrypoint."""
    args = parse_args(argv)
    storage = Storage(args.db)
    driver = UiautomatorDriver()
    bot = TikTokStreakBot(storage, driver)

    try:
        if args.run_now:
            bot.run_streak_batch(
                dry_run=True if args.dry_run else None,
                cb=lambda msg: print(msg, flush=True),
            )
            return 0

        if args.daemon:
            scheduler = StreakScheduler(
                storage, bot, on_status=lambda msg: print(msg, flush=True)
            )
            print("TikTok Streak Daemon is running. Press Ctrl+C to stop.", flush=True)
            try:
                asyncio.run(scheduler.run_forever(poll_seconds=15.0))
            except KeyboardInterrupt:
                print("Daemon stopped.", flush=True)
            return 0

        menu = SimpleTerminalMenu(storage=storage, driver=driver)
        menu.run()
        return 0
    finally:
        storage.close()


if __name__ == "__main__":
    sys.exit(main())
