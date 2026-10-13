from __future__ import annotations

from dataclasses import dataclass

from idm.storage.models import DownloadStatus


@dataclass(slots=True)
class DownloadEvent:
    """Emitted from engine threads to whoever is listening (GUI adapter, CLI, tests).

    Consumers must not assume this arrives on any particular thread.
    """

    download_id: int
    status: DownloadStatus
    downloaded_bytes: int
    total_size: int
    speed_bytes_per_sec: float = 0.0
    eta_seconds: float | None = None
    error_message: str | None = None

    @property
    def progress_fraction(self) -> float | None:
        if self.total_size <= 0:
            return None
        return min(1.0, self.downloaded_bytes / self.total_size)
