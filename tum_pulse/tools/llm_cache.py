"""SQLite-backed LLM response cache with TTL support."""

import hashlib
import sqlite3
import time
from pathlib import Path

from tum_pulse.config import DB_PATH


class LLMCache:
    """Cache LLM responses by prompt fingerprint to avoid repeat Bedrock calls.

    Keys are md5(prompt[:600]) so semantically identical prompts always hit the same entry.
    TTL is per-entry; stale entries are ignored and overwritten on next set().
    """

    def __init__(self, db_path: str = DB_PATH) -> None:
        self._db = db_path
        self._init_table()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db)

    def _init_table(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_cache (
                    key       TEXT PRIMARY KEY,
                    value     TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _key(prompt: str, model: str = "") -> str:
        raw = f"{model}:{prompt[:600]}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, prompt: str, model: str = "") -> str | None:
        """Return cached response or None if missing/expired."""
        key = self._key(prompt, model)
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value, expires_at FROM llm_cache WHERE key = ?", (key,)
                ).fetchone()
            if row and time.time() < row[1]:
                return row[0]
        except Exception:
            pass
        return None

    def set(self, prompt: str, value: str, ttl_seconds: int, model: str = "") -> None:
        """Store a response. Overwrites any existing entry for the same key."""
        key = self._key(prompt, model)
        expires = time.time() + ttl_seconds
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO llm_cache (key, value, expires_at) VALUES (?, ?, ?)",
                    (key, value, expires),
                )
                conn.commit()
        except Exception:
            pass

    def invalidate(self, prompt: str, model: str = "") -> None:
        key = self._key(prompt, model)
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM llm_cache WHERE key = ?", (key,))
                conn.commit()
        except Exception:
            pass

    def purge_expired(self) -> int:
        """Delete expired entries. Returns number of rows removed."""
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "DELETE FROM llm_cache WHERE expires_at < ?", (time.time(),)
                )
                conn.commit()
                return cur.rowcount
        except Exception:
            return 0
