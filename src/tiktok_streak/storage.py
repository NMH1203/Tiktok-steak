"""SQLite persistence layer for contacts, message templates, schedule, and logs."""

from __future__ import annotations

import random
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from tiktok_streak.models import (
    Contact,
    MessageTemplate,
    ScannedRow,
    ScheduleConfig,
    SendLog,
)

DEFAULT_TEMPLATES = [
    "Giữ chuỗi nè {name} 🔥",
    "Hello {name}, điểm danh giữ chuỗi hôm nay nhé 👋",
    "Chúc {name} một ngày tốt lành nha ✨",
    "Nhắn nhẹ giữ chuỗi với {name} 😄",
]


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Storage:
    """Thread-safe SQLite store for application configuration and history."""

    def __init__(self, db_path: str | Path = "data/tiktok_streak.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL UNIQUE,
                    last_preview TEXT NOT NULL DEFAULT '',
                    streak_info TEXT NOT NULL DEFAULT '',
                    selected INTEGER NOT NULL DEFAULT 0,
                    last_sent_date TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schedule_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    target_time TEXT NOT NULL DEFAULT '20:00',
                    jitter_minutes INTEGER NOT NULL DEFAULT 20,
                    min_delay_sec INTEGER NOT NULL DEFAULT 4,
                    max_delay_sec INTEGER NOT NULL DEFAULT 10,
                    dry_run INTEGER NOT NULL DEFAULT 1,
                    device_serial TEXT NOT NULL DEFAULT '',
                    avoid_repeat_last INTEGER NOT NULL DEFAULT 1,
                    unlock_pin TEXT NOT NULL DEFAULT '',
                    auto_lock_after_run INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS send_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    contact_name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                );
                """
            )
            cur.execute("SELECT COUNT(*) AS cnt FROM schedule_config WHERE id = 1")
            if cur.fetchone()["cnt"] == 0:
                cur.execute("INSERT INTO schedule_config (id) VALUES (1)")

            # Migrate older databases lacking unlock columns
            existing_cols = {
                row["name"]
                for row in cur.execute("PRAGMA table_info(schedule_config)").fetchall()
            }
            if "unlock_pin" not in existing_cols:
                cur.execute(
                    "ALTER TABLE schedule_config ADD COLUMN unlock_pin TEXT NOT NULL DEFAULT ''"
                )
            if "auto_lock_after_run" not in existing_cols:
                cur.execute(
                    "ALTER TABLE schedule_config ADD COLUMN auto_lock_after_run INTEGER NOT NULL DEFAULT 1"
                )

            cur.execute("SELECT COUNT(*) AS cnt FROM templates")
            if cur.fetchone()["cnt"] == 0:
                now = _now_iso()
                cur.executemany(
                    "INSERT INTO templates (content, enabled, created_at) VALUES (?, 1, ?)",
                    [(tpl, now) for tpl in DEFAULT_TEMPLATES],
                )
            self._conn.commit()

    # --- Contacts ---

    def upsert_scanned_contacts(self, rows: list[ScannedRow]) -> list[Contact]:
        """Insert or update scanned contacts while preserving selection and send history."""
        now = _now_iso()
        with self._lock:
            cur = self._conn.cursor()
            for row in rows:
                if row.is_system or not row.display_name.strip():
                    continue
                cur.execute(
                    """
                    INSERT INTO contacts (display_name, last_preview, streak_info, selected, updated_at)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(display_name) DO UPDATE SET
                        last_preview = excluded.last_preview,
                        streak_info = CASE
                            WHEN excluded.streak_info != '' THEN excluded.streak_info
                            ELSE contacts.streak_info
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (row.display_name.strip(), row.last_preview, row.streak_info, now),
                )
            self._conn.commit()
        return self.list_contacts()

    def add_manual_contact(self, display_name: str, selected: bool = True) -> Contact:
        """Add or update a contact manually by display name."""
        name = display_name.strip()
        if not name:
            raise ValueError("Tên người nhận không được để trống.")
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO contacts (display_name, selected, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(display_name) DO UPDATE SET
                    selected = excluded.selected,
                    updated_at = excluded.updated_at
                """,
                (name, int(selected), now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM contacts WHERE display_name = ?", (name,)
            ).fetchone()
            return self._row_to_contact(row)

    def list_contacts(self, selected_only: bool = False) -> list[Contact]:
        """Return saved contacts ordered by selection state then display name."""
        sql = "SELECT * FROM contacts"
        if selected_only:
            sql += " WHERE selected = 1"
        sql += " ORDER BY selected DESC, display_name COLLATE NOCASE ASC"
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
            return [self._row_to_contact(r) for r in rows]

    def set_contact_selected(self, contact_id: int, selected: bool) -> None:
        """Toggle selection flag for a single contact."""
        with self._lock:
            self._conn.execute(
                "UPDATE contacts SET selected = ? WHERE id = ?",
                (int(selected), contact_id),
            )
            self._conn.commit()

    def set_all_contacts_selected(self, selected: bool) -> None:
        """Select or deselect all stored contacts."""
        with self._lock:
            self._conn.execute("UPDATE contacts SET selected = ?", (int(selected),))
            self._conn.commit()

    def delete_contact(self, contact_id: int) -> None:
        """Remove a contact from the database."""
        with self._lock:
            self._conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
            self._conn.commit()

    def mark_contact_sent(self, display_name: str, date_str: str) -> None:
        """Record the most recent date a streak message was sent to a contact."""
        with self._lock:
            self._conn.execute(
                "UPDATE contacts SET last_sent_date = ?, updated_at = ? WHERE display_name = ?",
                (date_str, _now_iso(), display_name),
            )
            self._conn.commit()

    @staticmethod
    def _row_to_contact(row: sqlite3.Row) -> Contact:
        return Contact(
            id=row["id"],
            display_name=row["display_name"],
            last_preview=row["last_preview"],
            streak_info=row["streak_info"],
            selected=bool(row["selected"]),
            last_sent_date=row["last_sent_date"],
            updated_at=row["updated_at"],
        )

    # --- Templates ---

    def list_templates(self, enabled_only: bool = False) -> list[MessageTemplate]:
        """Return message templates ordered by id."""
        sql = "SELECT * FROM templates"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id ASC"
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
            return [
                MessageTemplate(
                    id=r["id"],
                    content=r["content"],
                    enabled=bool(r["enabled"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def add_template(self, content: str, enabled: bool = True) -> MessageTemplate:
        """Insert a new randomizable message template."""
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Nội dung câu nhắn không được để trống.")
        now = _now_iso()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO templates (content, enabled, created_at) VALUES (?, ?, ?)",
                (cleaned, int(enabled), now),
            )
            self._conn.commit()
            return MessageTemplate(
                id=cur.lastrowid, content=cleaned, enabled=enabled, created_at=now
            )

    def update_template(
        self, template_id: int, content: str | None = None, enabled: bool | None = None
    ) -> None:
        """Update template text and/or enabled state."""
        with self._lock:
            row = self._conn.execute(
                "SELECT content, enabled FROM templates WHERE id = ?", (template_id,)
            ).fetchone()
            if row is None:
                return
            new_content = row["content"] if content is None else content.strip()
            if not new_content:
                raise ValueError("Nội dung câu nhắn không được để trống.")
            new_enabled = row["enabled"] if enabled is None else int(enabled)
            self._conn.execute(
                "UPDATE templates SET content = ?, enabled = ? WHERE id = ?",
                (new_content, new_enabled, template_id),
            )
            self._conn.commit()

    def delete_template(self, template_id: int) -> None:
        """Delete a message template by ID."""
        with self._lock:
            self._conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
            self._conn.commit()

    def pick_random_template(
        self, contact_name: str, avoid_repeat_last: bool = True
    ) -> str | None:
        """Pick an enabled template, avoiding the previous message sent to this contact."""
        templates = self.list_templates(enabled_only=True)
        if not templates:
            return None

        last_msg = None
        if avoid_repeat_last:
            with self._lock:
                row = self._conn.execute(
                    """
                    SELECT message FROM send_logs
                    WHERE contact_name = ? AND status IN ('SUCCESS', 'DRY_RUN')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (contact_name,),
                ).fetchone()
                if row:
                    last_msg = row["message"]

        candidates = [self.format_template(t.content, contact_name) for t in templates]
        if last_msg and len(candidates) > 1:
            filtered = [m for m in candidates if m != last_msg]
            if filtered:
                candidates = filtered
        return random.choice(candidates)

    @staticmethod
    def format_template(template_text: str, contact_name: str) -> str:
        """Substitute `{name}` safely without crashing on stray braces."""
        return template_text.replace("{name}", contact_name)

    # --- Schedule ---

    def get_schedule(self) -> ScheduleConfig:
        """Load the singleton schedule configuration."""
        with self._lock:
            r = self._conn.execute("SELECT * FROM schedule_config WHERE id = 1").fetchone()
            return ScheduleConfig(
                enabled=bool(r["enabled"]),
                target_time=r["target_time"],
                jitter_minutes=r["jitter_minutes"],
                min_delay_sec=r["min_delay_sec"],
                max_delay_sec=r["max_delay_sec"],
                dry_run=bool(r["dry_run"]),
                device_serial=r["device_serial"],
                avoid_repeat_last=bool(r["avoid_repeat_last"]),
                unlock_pin=r["unlock_pin"],
                auto_lock_after_run=bool(r["auto_lock_after_run"]),
            )

    def save_schedule(self, cfg: ScheduleConfig) -> None:
        """Persist updated schedule configuration."""
        with self._lock:
            self._conn.execute(
                """
                UPDATE schedule_config SET
                    enabled = ?,
                    target_time = ?,
                    jitter_minutes = ?,
                    min_delay_sec = ?,
                    max_delay_sec = ?,
                    dry_run = ?,
                    device_serial = ?,
                    avoid_repeat_last = ?,
                    unlock_pin = ?,
                    auto_lock_after_run = ?
                WHERE id = 1
                """,
                (
                    int(cfg.enabled),
                    cfg.target_time,
                    max(0, int(cfg.jitter_minutes)),
                    max(1, int(cfg.min_delay_sec)),
                    max(int(cfg.min_delay_sec), int(cfg.max_delay_sec)),
                    int(cfg.dry_run),
                    cfg.device_serial.strip(),
                    int(cfg.avoid_repeat_last),
                    cfg.unlock_pin,
                    int(cfg.auto_lock_after_run),
                ),
            )
            self._conn.commit()

    # --- Logs ---

    def add_log(
        self, contact_name: str, message: str, status: str, detail: str = ""
    ) -> SendLog:
        """Append an audit log entry."""
        ts = _now_iso()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO send_logs (timestamp, contact_name, message, status, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ts, contact_name, message, status, detail),
            )
            self._conn.commit()
            return SendLog(
                id=cur.lastrowid,
                timestamp=ts,
                contact_name=contact_name,
                message=message,
                status=status,
                detail=detail,
            )

    def list_logs(self, limit: int = 100) -> list[SendLog]:
        """Return newest audit logs first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM send_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                SendLog(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    contact_name=r["contact_name"],
                    message=r["message"],
                    status=r["status"],
                    detail=r["detail"],
                )
                for r in rows
            ]
