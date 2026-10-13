from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from idm.storage.db import Database
from idm.storage.models import DownloadRecord, DownloadStatus, SegmentRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_download(row: sqlite3.Row) -> DownloadRecord:
    return DownloadRecord(
        id=row["id"],
        url=row["url"],
        filename=row["filename"],
        destination_path=row["destination_path"],
        category=row["category"],
        total_size=row["total_size"],
        status=DownloadStatus(row["status"]),
        downloaded_bytes=row["downloaded_bytes"],
        connections=row["connections"],
        priority=row["priority"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        scheduled_at=row["scheduled_at"],
        error_message=row["error_message"],
        retry_count=row["retry_count"],
        supports_ranges=bool(row["supports_ranges"]),
        speed_limit_bytes=row["speed_limit_bytes"],
        source=row["source"],
        kind=row["kind"],
        options=row["options"],
    )


def _row_to_segment(row: sqlite3.Row) -> SegmentRecord:
    return SegmentRecord(
        id=row["id"],
        download_id=row["download_id"],
        index=row["seg_index"],
        start_byte=row["start_byte"],
        end_byte=row["end_byte"],
        downloaded_bytes=row["downloaded_bytes"],
    )


class DownloadRepository:
    """All persistence for downloads, segments, and settings."""

    def __init__(self, db: Database):
        self._db = db

    # -- downloads ---------------------------------------------------

    def create_download(self, record: DownloadRecord) -> int:
        with self._db.lock, self._db.conn:
            cur = self._db.conn.execute(
                """
                INSERT INTO downloads
                    (url, filename, destination_path, category, total_size,
                     status, downloaded_bytes, connections, priority,
                     created_at, scheduled_at, supports_ranges, speed_limit_bytes,
                     source, kind, options)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.url, record.filename, record.destination_path,
                    record.category, record.total_size, record.status.value,
                    record.downloaded_bytes, record.connections, record.priority,
                    record.created_at or _now_iso(), record.scheduled_at,
                    int(record.supports_ranges), record.speed_limit_bytes,
                    record.source, record.kind, record.options,
                ),
            )
            download_id = cur.lastrowid
            for seg in record.segments:
                self._insert_segment(download_id, seg)
            return download_id

    def _insert_segment(self, download_id: int, seg: SegmentRecord) -> int:
        cur = self._db.conn.execute(
            """
            INSERT INTO segments
                (download_id, seg_index, start_byte, end_byte, downloaded_bytes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (download_id, seg.index, seg.start_byte, seg.end_byte, seg.downloaded_bytes),
        )
        return cur.lastrowid

    def get_download(self, download_id: int) -> DownloadRecord | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM downloads WHERE id = ?", (download_id,)
            ).fetchone()
            if row is None:
                return None
            record = _row_to_download(row)
            record.segments = self.get_segments(download_id)
            return record

    def get_segments(self, download_id: int) -> list[SegmentRecord]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM segments WHERE download_id = ? ORDER BY seg_index",
                (download_id,),
            ).fetchall()
            return [_row_to_segment(r) for r in rows]

    def list_downloads(
        self, statuses: list[DownloadStatus] | None = None
    ) -> list[DownloadRecord]:
        with self._db.lock:
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                rows = self._db.conn.execute(
                    f"SELECT * FROM downloads WHERE status IN ({placeholders}) "
                    "ORDER BY priority DESC, created_at ASC",
                    [s.value for s in statuses],
                ).fetchall()
            else:
                rows = self._db.conn.execute(
                    "SELECT * FROM downloads ORDER BY priority DESC, created_at ASC"
                ).fetchall()
            return [_row_to_download(r) for r in rows]

    def find_active_download(
        self, url: str, destination_path: str
    ) -> DownloadRecord | None:
        """Is there already a non-terminal download for this URL or, more
        importantly, this exact destination path? Two DownloadTasks writing
        to the same file concurrently would corrupt it, so this is checked
        before any new download is queued, not just for user convenience."""
        active = (
            DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING,
            DownloadStatus.PAUSED, DownloadStatus.SCHEDULED,
        )
        with self._db.lock:
            placeholders = ",".join("?" for _ in active)
            row = self._db.conn.execute(
                f"""
                SELECT * FROM downloads
                WHERE status IN ({placeholders})
                  AND (url = ? OR destination_path = ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                [*(s.value for s in active), url, destination_path],
            ).fetchone()
            return _row_to_download(row) if row else None

    def update_status(
        self, download_id: int, status: DownloadStatus, error_message: str | None = None
    ) -> None:
        with self._db.lock, self._db.conn:
            completed_at = _now_iso() if status == DownloadStatus.COMPLETED else None
            self._db.conn.execute(
                """
                UPDATE downloads
                SET status = ?, error_message = ?,
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (status.value, error_message, completed_at, download_id),
            )

    def update_progress(self, download_id: int, downloaded_bytes: int) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "UPDATE downloads SET downloaded_bytes = ? WHERE id = ?",
                (downloaded_bytes, download_id),
            )

    def update_total_size(self, download_id: int, total_size: int, supports_ranges: bool) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "UPDATE downloads SET total_size = ?, supports_ranges = ? WHERE id = ?",
                (total_size, int(supports_ranges), download_id),
            )

    def update_file(self, download_id: int, filename: str, destination_path: str, category: str) -> None:
        """A video's real file name/extension is only known once yt-dlp has finished."""
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "UPDATE downloads SET filename = ?, destination_path = ?, category = ? WHERE id = ?",
                (filename, destination_path, category, download_id),
            )

    def increment_retry(self, download_id: int) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "UPDATE downloads SET retry_count = retry_count + 1 WHERE id = ?",
                (download_id,),
            )

    def set_download_speed_limit(self, download_id: int, bytes_per_sec: int | None) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "UPDATE downloads SET speed_limit_bytes = ? WHERE id = ?",
                (bytes_per_sec, download_id),
            )

    def set_priority(self, download_id: int, priority: int) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "UPDATE downloads SET priority = ? WHERE id = ?", (priority, download_id)
            )

    def delete_download(self, download_id: int) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute("DELETE FROM downloads WHERE id = ?", (download_id,))

    # -- segments ------------------------------------------------------

    def replace_segments(self, download_id: int, segments: list[SegmentRecord]) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "DELETE FROM segments WHERE download_id = ?", (download_id,)
            )
            for seg in segments:
                self._insert_segment(download_id, seg)

    def update_segment_progress(self, segment_id: int, downloaded_bytes: int) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "UPDATE segments SET downloaded_bytes = ? WHERE id = ?",
                (downloaded_bytes, segment_id),
            )

    # -- settings --------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._db.lock, self._db.conn:
            self._db.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
