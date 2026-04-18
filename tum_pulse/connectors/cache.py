"""Smart caching layer for TUMonline, Moodle, and recommendations.

Manages TTLs, hierarchical course storage, and fast lookups.
No latency added - uses SQLite for instant cache hits.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Any

from tum_pulse.config import DB_PATH


class CacheManager:
    """Unified cache with TTL support for all connectors."""

    TUMONLINE_TTL_HOURS = 1
    MOODLE_TTL_HOURS = 1
    RECOMMENDATIONS_TTL_HOURS = 24  # Dynamic, so refresh daily

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_cache_tables()

    def _init_cache_tables(self):
        """Create cache tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- TUMonline cache (courses, grades, achievements)
                CREATE TABLE IF NOT EXISTS tumonline_cache (
                    key            TEXT PRIMARY KEY,
                    data           TEXT NOT NULL,
                    cached_at      TEXT DEFAULT (datetime('now')),
                    ttl_hours      INTEGER DEFAULT 1
                );

                -- Moodle course cache (separate current/historical)
                CREATE TABLE IF NOT EXISTS moodle_courses_cache (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id     TEXT NOT NULL,
                    course_name   TEXT NOT NULL,
                    category      TEXT NOT NULL,  -- 'current' or 'historical'
                    materials     TEXT,  -- JSON: [{"name": "...", "url": "...", "type": "..."}]
                    cached_at     TEXT DEFAULT (datetime('now')),
                    ttl_hours     INTEGER DEFAULT 1
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_moodle_unique
                    ON moodle_courses_cache (course_id, category);

                -- Recommendation cache (deterministic based on profile)
                CREATE TABLE IF NOT EXISTS recommendations_cache (
                    user_id       TEXT PRIMARY KEY,
                    recommendations TEXT NOT NULL,  -- JSON
                    cached_at     TEXT DEFAULT (datetime('now')),
                    ttl_hours     INTEGER DEFAULT 24
                );
            """)

    # ─────────────────────────────────────────────────────────────────────
    # TUMonline Cache
    # ─────────────────────────────────────────────────────────────────────

    def save_tumonline_courses(self, current: list[dict], historical: list[dict]) -> None:
        """Cache TUMonline courses (current + historical)."""
        data = {"current": current, "historical": historical}
        self._set_cache("tumonline_courses", data, ttl_hours=self.TUMONLINE_TTL_HOURS)

    def get_tumonline_courses(self) -> Optional[dict]:
        """Get cached TUMonline courses (current + historical)."""
        return self._get_cache("tumonline_courses")

    def save_tumonline_grades(self, grades: dict) -> None:
        """Cache TUMonline grades (grade_name -> grade_value)."""
        self._set_cache("tumonline_grades", grades, ttl_hours=self.TUMONLINE_TTL_HOURS)

    def get_tumonline_grades(self) -> Optional[dict]:
        """Get cached TUMonline grades."""
        return self._get_cache("tumonline_grades")

    def save_tumonline_achievements(self, achievements: list[dict]) -> None:
        """Cache TUMonline achievements."""
        self._set_cache("tumonline_achievements", achievements, ttl_hours=self.TUMONLINE_TTL_HOURS)

    def get_tumonline_achievements(self) -> Optional[list]:
        """Get cached TUMonline achievements."""
        return self._get_cache("tumonline_achievements")

    # ─────────────────────────────────────────────────────────────────────
    # Moodle Cache (hierarchical: current vs historical)
    # ─────────────────────────────────────────────────────────────────────

    def save_moodle_current_course(self, course_id: str, course_name: str, materials: list[dict]) -> None:
        """Save a current semester Moodle course with its materials."""
        self._save_moodle_course(course_id, course_name, "current", materials)

    def save_moodle_historical_course(self, course_id: str, course_name: str, materials: list[dict]) -> None:
        """Save a previous semester Moodle course with its materials."""
        self._save_moodle_course(course_id, course_name, "historical", materials)

    def _save_moodle_course(self, course_id: str, course_name: str, category: str, materials: list[dict]) -> None:
        """Internal: save Moodle course with category."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO moodle_courses_cache 
                   (course_id, course_name, category, materials, cached_at) 
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                (course_id, course_name, category, json.dumps(materials))
            )

    def get_moodle_current_courses(self) -> dict[str, dict]:
        """Get all current semester courses: {course_id: {name, materials}}."""
        return self._get_moodle_courses_by_category("current")

    def get_moodle_historical_courses(self) -> dict[str, dict]:
        """Get all previous semester courses: {course_id: {name, materials}}."""
        return self._get_moodle_courses_by_category("historical")

    def _get_moodle_courses_by_category(self, category: str) -> dict[str, dict]:
        """Internal: get courses grouped by category."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT course_id, course_name, materials FROM moodle_courses_cache WHERE category = ?",
                (category,)
            ).fetchall()

        result = {}
        for course_id, course_name, materials_json in rows:
            result[course_id] = {
                "name": course_name,
                "materials": json.loads(materials_json) if materials_json else []
            }
        return result

    def get_moodle_course_materials(self, course_id: str) -> list[dict]:
        """Get materials for a specific course (fast lookup)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT materials FROM moodle_courses_cache WHERE course_id = ?",
                (course_id,)
            ).fetchone()

        if row and row[0]:
            return json.loads(row[0])
        return []

    # ─────────────────────────────────────────────────────────────────────
    # Recommendation Cache (deterministic: same profile → same recs)
    # ─────────────────────────────────────────────────────────────────────

    def save_recommendations(self, user_id: str, recommendations: list[dict]) -> None:
        """Cache recommendations for a user (deterministic)."""
        self._set_cache(
            f"recommendations_{user_id}",
            recommendations,
            ttl_hours=self.RECOMMENDATIONS_TTL_HOURS,
            table="recommendations_cache"
        )

    def get_recommendations(self, user_id: str) -> Optional[list]:
        """Get cached recommendations (None if expired/missing)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT recommendations, cached_at, ttl_hours FROM recommendations_cache WHERE user_id = ?",
                (user_id,)
            ).fetchone()

        if not row:
            return None

        recommendations_json, cached_at_str, ttl_hours = row
        if self._is_expired(cached_at_str, ttl_hours):
            return None

        return json.loads(recommendations_json)

    # ─────────────────────────────────────────────────────────────────────
    # Internal cache helpers
    # ─────────────────────────────────────────────────────────────────────

    def _set_cache(self, key: str, data: Any, ttl_hours: int, table: str = "tumonline_cache") -> None:
        """Set a cache entry with TTL."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} (key, data, cached_at, ttl_hours) VALUES (?, ?, datetime('now'), ?)",
                (key, json.dumps(data), ttl_hours)
            )
            conn.commit()

    def _get_cache(self, key: str, table: str = "tumonline_cache") -> Optional[Any]:
        """Get a cache entry if not expired."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT data, cached_at, ttl_hours FROM {table} WHERE key = ?",
                (key,)
            ).fetchone()

        if not row:
            return None

        data_json, cached_at_str, ttl_hours = row
        if self._is_expired(cached_at_str, ttl_hours):
            return None

        return json.loads(data_json)

    def _is_expired(self, cached_at_str: str, ttl_hours: int) -> bool:
        """Check if cache entry has expired."""
        try:
            cached_at = datetime.fromisoformat(cached_at_str)
            expires_at = cached_at + timedelta(hours=ttl_hours)
            return datetime.now() > expires_at
        except Exception:
            return True

    # ─────────────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────────────

    def clear_tumonline_cache(self) -> None:
        """Clear all TUMonline cache entries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM tumonline_cache")

    def clear_moodle_cache(self) -> None:
        """Clear all Moodle cache entries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM moodle_courses_cache")

    def cache_stats(self) -> dict:
        """Get cache statistics for debugging."""
        with sqlite3.connect(self.db_path) as conn:
            tumonline_count = conn.execute("SELECT COUNT(*) FROM tumonline_cache").fetchone()[0]
            moodle_count = conn.execute("SELECT COUNT(*) FROM moodle_courses_cache").fetchone()[0]
            rec_count = conn.execute("SELECT COUNT(*) FROM recommendations_cache").fetchone()[0]

        return {
            "tumonline_entries": tumonline_count,
            "moodle_entries": moodle_count,
            "recommendations_entries": rec_count,
        }
