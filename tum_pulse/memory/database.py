"""SQLite shared memory layer for TUM Pulse."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from tum_pulse.config import DB_PATH


class SQLiteMemory:
    """Manages all persistent state for TUM Pulse agents."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        """Initialise the memory layer and ensure schema exists."""
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create all tables if they do not yet exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS deadlines (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    title        TEXT    NOT NULL,
                    course       TEXT,
                    deadline_date TEXT,
                    source       TEXT,
                    created_at   TEXT    DEFAULT (datetime('now'))
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_deadlines_unique
                    ON deadlines (title, source, deadline_date);

                CREATE TABLE IF NOT EXISTS student_profile (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS scraped_content (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    source     TEXT,
                    url        TEXT,
                    content    TEXT,
                    scraped_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    message       TEXT,
                    deadline_date TEXT,
                    sent          INTEGER DEFAULT 0,
                    created_at    TEXT    DEFAULT (datetime('now'))
                );
            """)

    # ------------------------------------------------------------------
    # Deadlines
    # ------------------------------------------------------------------

    def save_deadline(
        self,
        title: str,
        course: str,
        deadline_date: str,
        source: str,
    ) -> int:
        """Insert a deadline and return its new row id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO deadlines (title, course, deadline_date, source) VALUES (?, ?, ?, ?)",
                (title, course, deadline_date, source),
            )
            return cur.lastrowid or 0

    def get_upcoming_deadlines(self, days: int = 7) -> list[dict]:
        """Return deadlines within the next *days* days, sorted by date."""
        cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM deadlines WHERE deadline_date BETWEEN ? AND ? ORDER BY deadline_date",
                (today, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Student profile
    # ------------------------------------------------------------------

    def save_profile(self, key: str, value: Any) -> None:
        """Upsert a profile value (serialised as JSON)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO student_profile (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def get_profile(self, key: str) -> Optional[Any]:
        """Return a profile value, or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM student_profile WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    # ------------------------------------------------------------------
    # Scraped content
    # ------------------------------------------------------------------

    def save_content(self, source: str, url: str, content: str) -> int:
        """Store a scraped page or document."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO scraped_content (source, url, content) VALUES (?, ?, ?)",
                (source, url, content),
            )
            return cur.lastrowid

    def get_content_by_source(self, source: str) -> list[dict]:
        """Return all scraped items for the given source identifier."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM scraped_content WHERE source = ? ORDER BY scraped_at DESC",
                (source,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def mark_alert_sent(self, alert_id: int) -> None:
        """Mark an alert as sent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE alerts SET sent = 1 WHERE id = ?", (alert_id,))

    def create_alert(self, message: str, deadline_date: str) -> int:
        """Create a new (unsent) alert and return its id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO alerts (message, deadline_date) VALUES (?, ?)",
                (message, deadline_date),
            )
            return cur.lastrowid

    def get_pending_alerts(self) -> list[dict]:
        """Return all alerts that have not yet been sent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM alerts WHERE sent = 0 ORDER BY deadline_date"
            ).fetchall()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    db = SQLiteMemory()
    db.save_deadline("Homework 1", "Analysis 2", "2026-04-25", "test")
    print("Upcoming deadlines:", db.get_upcoming_deadlines(30))
    db.save_profile("name", "Max Mustermann")
    print("Profile name:", db.get_profile("name"))
    print("Database initialised at", DB_PATH)
