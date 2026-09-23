"""Tiny SQLite cache for HTTP responses.

Pageviews of closed months practically never change, so they are cached for a
long time; this is what makes follow-up questions ("add Slovak", "now 5 years")
cheap: only the missing series are downloaded.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from .paths import cache_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS http (
    url TEXT PRIMARY KEY,
    status INTEGER NOT NULL,
    body TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    expires_at REAL
)
"""


class Cache:
    def __init__(self, path: Path | None = None):
        self.path = path or cache_dir() / "http-cache.sqlite"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, url: str) -> tuple[int, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status, body, expires_at FROM http WHERE url = ?", (url,)
            ).fetchone()
        if row is None:
            return None
        status, body, expires_at = row
        if expires_at is not None and expires_at < time.time():
            return None
        return status, body

    def put(self, url: str, status: int, body: str, ttl: float | None) -> None:
        now = time.time()
        expires = None if ttl is None else now + ttl
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO http (url, status, body, fetched_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (url, status, body, now, expires),
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            n, size = self._conn.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(body)), 0) FROM http").fetchone()
        return {"entries": n, "bytes": size, "path": str(self.path)}

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM http")
            self._conn.commit()
