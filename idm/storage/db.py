"""SQLite connection management and schema."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    filename        TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'Other',
    total_size      INTEGER NOT NULL DEFAULT -1,
    status          TEXT NOT NULL DEFAULT 'queued',
    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
    connections     INTEGER NOT NULL DEFAULT 8,
    priority        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,
    scheduled_at    TEXT,
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    supports_ranges INTEGER NOT NULL DEFAULT 1,
    speed_limit_bytes INTEGER,
    source          TEXT NOT NULL DEFAULT 'Direct link',
    kind            TEXT NOT NULL DEFAULT 'file',
    options         TEXT
);

CREATE TABLE IF NOT EXISTS segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    download_id     INTEGER NOT NULL REFERENCES downloads(id) ON DELETE CASCADE,
    seg_index       INTEGER NOT NULL,
    start_byte      INTEGER NOT NULL,
    end_byte        INTEGER NOT NULL,
    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
    UNIQUE(download_id, seg_index)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_segments_download_id ON segments(download_id);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
"""


class Database:
    """Thread-safe-enough SQLite wrapper: one connection per thread via a lock.

    SQLite connections aren't shared across threads by default; the engine
    touches this from multiple worker threads (progress updates) plus the
    GUI thread, so a single connection opened with check_same_thread=False
    guarded by a lock keeps things simple and correct for our write volume.
    """

    def __init__(self, path: str | Path):
        self._path = str(path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            # databases created before video support lack these columns
            existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(downloads)")}
            for column, ddl in (("source", "TEXT NOT NULL DEFAULT 'Direct link'"),
                                ("kind", "TEXT NOT NULL DEFAULT 'file'"),
                                ("options", "TEXT")):
                if column not in existing:
                    self._conn.execute(f"ALTER TABLE downloads ADD COLUMN {column} {ddl}")

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        with self._lock:
            self._conn.close()
