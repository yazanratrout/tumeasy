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

                -- Course material metadata cached from Moodle on login
                CREATE TABLE IF NOT EXISTS course_materials (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_name TEXT NOT NULL,
                    file_name   TEXT NOT NULL,
                    url         TEXT,
                    file_type   TEXT,
                    fetched_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_materials_unique
                    ON course_materials (course_name, file_name);

                -- Key/value store for cache timestamps and fetch state
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    key   TEXT PRIMARY KEY,
                    value TEXT
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

    def clear_deadlines(self, source: str | None = None) -> int:
        """Delete deadlines from the database.

        Args:
            source: If provided, only delete deadlines from this source
                    (e.g. 'mock', 'tumonline', 'moodle').
                    If None, deletes ALL deadlines.

        Returns:
            Number of rows deleted.
        """
        with sqlite3.connect(self.db_path) as conn:
            if source:
                cur = conn.execute(
                    "DELETE FROM deadlines WHERE source = ?", (source,)
                )
            else:
                cur = conn.execute("DELETE FROM deadlines")
            return cur.rowcount

    def get_upcoming_deadlines_filtered(
        self, days: int = 7, enrolled_courses: list[str] | None = None
    ) -> list[dict]:
        """Return upcoming deadlines filtered by enrolled courses.

        Same as get_upcoming_deadlines() but applies keyword filtering
        against the student's enrolled course list so mock/irrelevant
        deadlines are excluded.

        Args:
            days: Number of days ahead to look.
            enrolled_courses: List of course name strings to filter by.
                              If None or empty, returns all deadlines.

        Returns:
            Filtered and sorted list of deadline dicts.
        """
        deadlines = self.get_upcoming_deadlines(days=days)

        if not enrolled_courses:
            return deadlines

        _GENERIC = {
            "introduction", "advanced", "applied", "practical",
            "fundamentals", "basics", "overview", "seminar",
            "lecture", "course", "study", "studies", "special",
            "topics", "selected", "principles",
        }
        kws: set[str] = set()
        for name in enrolled_courses:
            for word in name.split():
                w = word.lower().rstrip("0123456789")
                if len(w) > 3 and w not in _GENERIC:
                    kws.add(w)

        if not kws:
            return deadlines

        return [
            d for d in deadlines
            if d["title"].startswith("Exam Registration") or
            any(
                kw in (d["title"] + " " + d.get("course", "")).lower()
                for kw in kws
            )
        ]

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

    # ------------------------------------------------------------------
    # Course materials cache
    # ------------------------------------------------------------------

    def save_course_materials(self, course_name: str, materials: list[dict]) -> None:
        """Replace all cached materials for a course (upsert by course+file_name)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM course_materials WHERE course_name = ?",
                (course_name,)
            )
            conn.executemany(
                "INSERT OR REPLACE INTO course_materials "
                "(course_name, file_name, url, file_type) VALUES (?, ?, ?, ?)",
                [
                    (
                        course_name,
                        m.get("name", ""),
                        m.get("url", ""),
                        m.get("file_type", "pdf"),
                    )
                    for m in materials
                ],
            )

    def get_course_materials(self, course_name: str) -> list[dict]:
        """Return cached material metadata for a course."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT file_name AS name, url, file_type FROM course_materials "
                "WHERE course_name = ? ORDER BY file_name",
                (course_name,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_course_materials(self) -> dict[str, list[dict]]:
        """Return all cached materials grouped by course name."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT course_name, file_name AS name, url, file_type "
                "FROM course_materials ORDER BY course_name, file_name"
            ).fetchall()
        result: dict[str, list[dict]] = {}
        for r in rows:
            d = dict(r)
            course = d.pop("course_name")
            result.setdefault(course, []).append(d)
        return result

    # ------------------------------------------------------------------
    # Cache metadata (last_fetched, fetch status)
    # ------------------------------------------------------------------

    def save_cache_meta(self, key: str, value: str) -> None:
        """Store a key/value pair in the cache_metadata table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO cache_metadata (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_cache_meta(self, key: str) -> Optional[str]:
        """Retrieve a value from cache_metadata by key."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM cache_metadata WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def save_last_fetched(self, iso_timestamp: str) -> None:
        """Record the timestamp of the last successful data fetch."""
        self.save_cache_meta("last_fetched", iso_timestamp)

    def get_last_fetched(self) -> Optional[str]:
        """Return the ISO timestamp of the last successful data fetch, or None."""
        return self.get_cache_meta("last_fetched")

    def get_deadlines_for_range(self, from_date: str, to_date: str) -> list[dict]:
        """Return deadlines within an explicit date range (ISO YYYY-MM-DD)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM deadlines WHERE deadline_date BETWEEN ? AND ? "
                "ORDER BY deadline_date",
                (from_date, to_date),
            ).fetchall()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    db = SQLiteMemory()
    db.save_deadline("Homework 1", "Analysis 2", "2026-04-25", "test")
    print("Upcoming deadlines:", db.get_upcoming_deadlines(30))
    db.save_profile("name", "Max Mustermann")
    print("Profile name:", db.get_profile("name"))
    print("Database initialised at", DB_PATH)
