from __future__ import annotations

import os
import threading
from typing import Callable

from idm.core.errors import DuplicateDownloadError
from idm.core.events import DownloadEvent
from idm.core.http import filename_for
from idm.core.speed_limiter import SpeedLimiter
from idm.core.task import DownloadTask
from idm.storage.models import DownloadRecord, DownloadStatus
from idm.storage.paths import category_folder, category_for_extension, sanitize_filename
from idm.storage.repository import DownloadRepository

ACTIVE_STATUSES = (DownloadStatus.DOWNLOADING,)
TERMINAL_STATUSES = (
    DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELED,
)

EventListener = Callable[[DownloadEvent], None]


class DownloadManager:
    """Owns the queue: dispatch order, concurrency cap, global throttle.

    One DownloadManager per process. GUI (or a CLI harness) registers a
    listener to receive DownloadEvents; it never talks to DownloadTask
    directly.
    """

    def __init__(
        self,
        repository: DownloadRepository,
        downloads_root,
        max_concurrent: int = 3,
        global_speed_limit_bytes: int | None = None,
        task_factory: Callable[..., DownloadTask] | None = None,
    ):
        self._repo = repository
        self._downloads_root = downloads_root
        self._max_concurrent = max_concurrent
        self._global_limiter = SpeedLimiter(global_speed_limit_bytes)
        # Injectable so tests can exercise dispatch policy (concurrency cap,
        # priority order, pause freeing a slot) with a controllable fake,
        # instead of racing real HTTP requests against real thread timing.
        self._task_factory = task_factory or _default_task_factory

        self._lock = threading.RLock()
        self._tasks: dict[int, DownloadTask] = {}
        self._listeners: list[EventListener] = []
        self._queue_running = True

    # -- configuration ---------------------------------------------------

    def add_listener(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def set_max_concurrent(self, n: int) -> None:
        with self._lock:
            self._max_concurrent = max(1, n)
        self._dispatch()

    def set_global_speed_limit(self, bytes_per_sec: int | None) -> None:
        self._global_limiter.set_rate(bytes_per_sec)

    def start_queue(self) -> None:
        with self._lock:
            self._queue_running = True
        self._dispatch()

    def stop_queue(self) -> None:
        """Stop launching new downloads; does not pause ones already running."""
        with self._lock:
            self._queue_running = False

    # -- adding downloads --------------------------------------------------

    def add_download(
        self,
        url: str,
        destination_dir: str | None = None,
        filename: str | None = None,
        category: str | None = None,
        connections: int = 8,
        start_immediately: bool = True,
        scheduled_at: str | None = None,
        speed_limit_bytes: int | None = None,
        kind: str = "file",
        source: str = "Direct link",
        options: str | None = None,
    ) -> DownloadRecord:
        """Create a queue entry. Probing (size/filename/range support) is
        deferred to the task's own start() unless filename was already
        resolved by the caller (e.g. the Add Download dialog probed it to
        show the user before confirming)."""
        # Sanitize unconditionally, regardless of where `filename` came from
        # (a GUI text field the user could type anything into, a probed
        # Content-Disposition header the *server* controls, or a bare URL
        # fallback) -- this is the one choke point every caller passes
        # through on the way to an actual filesystem write.
        resolved_filename = sanitize_filename(filename or _filename_hint_from_url(url))
        resolved_category = category or category_for_extension(resolved_filename)
        if destination_dir:
            dest_dir = destination_dir
        else:
            dest_dir = str(category_folder(self._downloads_root, resolved_category))

        destination_path = os.path.join(dest_dir, resolved_filename)
        # Defense in depth: sanitize_filename() already strips separators and
        # drive prefixes so this can't actually trigger today, but a future
        # change to how destination_path is built shouldn't silently regress
        # into writing outside the chosen download folder.
        if os.path.dirname(os.path.normpath(destination_path)) != os.path.normpath(dest_dir):
            raise ValueError(f"resolved destination escaped the download folder: {destination_path!r}")

        # Two DownloadTasks racing to preallocate and write the same
        # destination_path would corrupt each other's output, not just
        # confuse the user -- refuse before creating the DB record.
        existing = self._repo.find_active_download(url=url, destination_path=destination_path)
        if existing is not None:
            raise DuplicateDownloadError(existing)

        status = DownloadStatus.SCHEDULED if scheduled_at else DownloadStatus.QUEUED
        record = DownloadRecord(
            id=None, url=url, filename=resolved_filename,
            destination_path=destination_path, category=resolved_category,
            total_size=-1, status=status, connections=connections,
            scheduled_at=scheduled_at, speed_limit_bytes=speed_limit_bytes,
            kind=kind, source=source, options=options,
        )
        record.id = self._repo.create_download(record)

        if start_immediately and not scheduled_at:
            self._dispatch()
        return record

    def load_persisted_queue(self) -> None:
        """Call once at startup: anything left DOWNLOADING when the app died
        goes back to QUEUED so it can be resumed by the dispatcher."""
        with self._lock:
            for record in self._repo.list_downloads([DownloadStatus.DOWNLOADING]):
                self._repo.update_status(record.id, DownloadStatus.QUEUED)
        self._dispatch()

    # -- per-download control ------------------------------------------------

    def pause(self, download_id: int) -> None:
        # Pop (not get): a paused task no longer occupies a concurrency slot,
        # and _dispatch() below must see the freed slot immediately.
        with self._lock:
            task = self._tasks.pop(download_id, None)
        if task:
            task.pause()
        else:
            # No running task means DownloadTask.pause() never runs, so it's
            # on us to emit the event ourselves -- otherwise the DB updates
            # but the GUI table (which only redraws on DownloadEvents) never
            # finds out and the row silently keeps showing the old status.
            self._repo.update_status(download_id, DownloadStatus.PAUSED)
            self._emit_status_event(download_id, DownloadStatus.PAUSED)
        self._dispatch()

    def resume(self, download_id: int) -> None:
        with self._lock:
            self._repo.update_status(download_id, DownloadStatus.QUEUED)
        self._emit_status_event(download_id, DownloadStatus.QUEUED)
        self._dispatch()

    def cancel(self, download_id: int) -> None:
        task = self._tasks.get(download_id)
        if task:
            task.cancel()
        else:
            self._repo.update_status(download_id, DownloadStatus.CANCELED)
            self._emit_status_event(download_id, DownloadStatus.CANCELED)
        self._dispatch()

    def retry(self, download_id: int) -> None:
        with self._lock:
            self._repo.update_status(download_id, DownloadStatus.QUEUED)
        self._emit_status_event(download_id, DownloadStatus.QUEUED)
        self._dispatch()

    def remove(self, download_id: int) -> None:
        task = self._tasks.pop(download_id, None)
        if task:
            task.cancel()
        self._repo.delete_download(download_id)

    def set_priority(self, download_id: int, priority: int) -> None:
        self._repo.set_priority(download_id, priority)
        self._dispatch()

    def set_download_speed_limit(self, download_id: int, bytes_per_sec: int | None) -> None:
        self._repo.set_download_speed_limit(download_id, bytes_per_sec)
        task = self._tasks.get(download_id)
        if task:
            task.set_speed_limit(bytes_per_sec)

    # -- dispatch loop -----------------------------------------------------

    def _dispatch(self) -> None:
        with self._lock:
            if not self._queue_running:
                return
            # self._tasks holds exactly the downloads occupying a concurrency
            # slot (added synchronously in _launch, removed on pause/terminal
            # via _handle_event) -- using is_running() here would race with
            # the launch thread not having created its futures yet.
            capacity = self._max_concurrent - len(self._tasks)
            if capacity <= 0:
                return

            queued = self._repo.list_downloads([DownloadStatus.QUEUED])
            for record in queued[:capacity]:
                self._launch(record)

    def _launch(self, record: DownloadRecord) -> None:
        record.segments = self._repo.get_segments(record.id)
        task = self._task_factory(
            record=record,
            repository=self._repo,
            on_event=self._handle_event,
            global_limiter=self._global_limiter,
        )
        self._tasks[record.id] = task
        thread = threading.Thread(
            target=task.start, name=f"idm-task-{record.id}", daemon=True,
        )
        thread.start()

    def _handle_event(self, event: DownloadEvent) -> None:
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                pass  # a broken listener must not take down the engine
        if event.status in TERMINAL_STATUSES:
            with self._lock:
                self._tasks.pop(event.download_id, None)
            self._dispatch()

    def _emit_status_event(self, download_id: int, status: DownloadStatus) -> None:
        """For status changes made directly against the DB (no DownloadTask
        involved to emit one itself) -- keeps listeners in sync with a status
        transition they'd otherwise never hear about."""
        record = self._repo.get_download(download_id)
        if record is None:
            return
        self._handle_event(DownloadEvent(
            download_id=download_id, status=status,
            downloaded_bytes=record.downloaded_bytes, total_size=record.total_size,
        ))


def _default_task_factory(record: DownloadRecord, **kwargs):
    if record.kind == "video":
        from idm.core.video_task import VideoTask  # yt-dlp is heavy; import only when needed
        return VideoTask(record=record, **kwargs)
    return DownloadTask(record=record, **kwargs)


def _filename_hint_from_url(url: str) -> str:
    return filename_for(url, None)
