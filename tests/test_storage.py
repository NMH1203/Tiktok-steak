"""Unit tests for SQLite storage layer."""

from __future__ import annotations

from pathlib import Path

from tiktok_streak.models import ScannedRow, ScheduleConfig
from tiktok_streak.storage import Storage


def test_storage_seeds_default_templates_and_schedule(tmp_path: Path) -> None:
    db = Storage(tmp_path / "test.db")
    try:
        templates = db.list_templates()
        assert len(templates) >= 3
        assert all(t.enabled for t in templates)

        cfg = db.get_schedule()
        assert cfg.enabled is False
        assert cfg.dry_run is True
        assert cfg.target_time == "20:00"
    finally:
        db.close()


def test_upsert_scanned_contacts_preserves_selection_and_sent_date(tmp_path: Path) -> None:
    db = Storage(tmp_path / "test.db")
    try:
        db.upsert_scanned_contacts(
            [
                ScannedRow(display_name="An Nguyen", last_preview="Hi", streak_info="🔥 12"),
                ScannedRow(display_name="Hoạt động mới", last_preview="...", is_system=True),
            ]
        )
        contacts = db.list_contacts()
        assert len(contacts) == 1
        assert contacts[0].display_name == "An Nguyen"
        assert contacts[0].selected is False

        db.set_contact_selected(contacts[0].id, True)  # type: ignore[arg-type]
        db.mark_contact_sent("An Nguyen", "2026-11-25")

        # Re-scan updates preview but keeps selection and sent date
        db.upsert_scanned_contacts(
            [ScannedRow(display_name="An Nguyen", last_preview="Đã gửi", streak_info="")]
        )
        updated = db.list_contacts()[0]
        assert updated.selected is True
        assert updated.last_sent_date == "2026-11-25"
        assert updated.last_preview == "Đã gửi"
        assert updated.streak_info == "🔥 12"
    finally:
        db.close()


def test_pick_random_template_avoids_repeating_last_message(tmp_path: Path) -> None:
    db = Storage(tmp_path / "test.db")
    try:
        # Remove defaults and keep only 2 templates
        for tpl in db.list_templates():
            db.delete_template(tpl.id)  # type: ignore[arg-type]
        db.add_template("Câu A cho {name}")
        db.add_template("Câu B cho {name}")

        db.add_log("Minh", "Câu A cho Minh", "SUCCESS")
        for _ in range(10):
            picked = db.pick_random_template("Minh", avoid_repeat_last=True)
            assert picked == "Câu B cho Minh"
    finally:
        db.close()


def test_save_and_load_schedule(tmp_path: Path) -> None:
    db = Storage(tmp_path / "test.db")
    try:
        cfg = ScheduleConfig(
            enabled=True,
            target_time="21:30",
            jitter_minutes=15,
            min_delay_sec=5,
            max_delay_sec=12,
            dry_run=False,
            device_serial="192.168.1.50:5555",
            avoid_repeat_last=False,
            unlock_pin="2580",
            auto_lock_after_run=False,
        )
        db.save_schedule(cfg)
        loaded = db.get_schedule()
        assert loaded == cfg
    finally:
        db.close()
