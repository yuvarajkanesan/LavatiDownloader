from __future__ import annotations

import threading
from datetime import datetime, timezone

from idm.storage.models import DownloadStatus
from idm.storage.repository import DownloadRepository

POLL_INTERVAL_SECONDS = 20.0


class DownloadScheduler:
    """Background poller that promotes SCHEDULED downloads to QUEUED once
    their scheduled_at time has arrived, then asks the manager to dispatch.
    """

    def __init__(self, repository: DownloadRepository, on_due: "callable[[], None]"):
        self._repo = repository
        self._on_due = on_due
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="idm-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop_event.wait(POLL_INTERVAL_SECONDS):
            self._promote_due()

    def _promote_due(self) -> None:
        now = datetime.now(timezone.utc)
        due_any = False
        for record in self._repo.list_downloads([DownloadStatus.SCHEDULED]):
            if record.scheduled_at and _parse_iso(record.scheduled_at) <= now:
                self._repo.update_status(record.id, DownloadStatus.QUEUED)
                due_any = True
        if due_any:
            self._on_due()


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
