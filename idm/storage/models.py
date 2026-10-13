from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    SCHEDULED = "scheduled"


@dataclass(slots=True)
class SegmentRecord:
    id: int | None
    download_id: int
    index: int
    start_byte: int
    end_byte: int
    downloaded_bytes: int = 0

    @property
    def size_unknown(self) -> bool:
        """end_byte == -1 is the sentinel for 'download until EOF' (size unknown)."""
        return self.end_byte < 0

    @property
    def remaining_bytes(self) -> int | None:
        if self.size_unknown:
            return None
        return max(0, (self.end_byte - self.start_byte + 1) - self.downloaded_bytes)

    @property
    def is_complete(self) -> bool:
        """Only meaningful for known-size segments; unknown-size segments are
        considered complete only when their stream ends (see download_segment)."""
        if self.size_unknown:
            return False
        return self.downloaded_bytes >= (self.end_byte - self.start_byte + 1)


@dataclass(slots=True)
class DownloadRecord:
    id: int | None
    url: str
    filename: str
    destination_path: str
    category: str
    total_size: int  # -1 if unknown
    status: DownloadStatus
    downloaded_bytes: int = 0
    connections: int = 8
    priority: int = 0
    created_at: str = ""
    completed_at: str | None = None
    scheduled_at: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    supports_ranges: bool = True
    speed_limit_bytes: int | None = None  # per-download throttle, None = unlimited
    source: str = "Direct link"  # site label shown under the file name
    kind: str = "file"  # "file" (segmented HTTP) or "video" (yt-dlp)
    options: str | None = None  # JSON, video downloads only
    segments: list[SegmentRecord] = field(default_factory=list)
