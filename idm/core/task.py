from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable

import requests

from idm.core.errors import UnrecoverableDownloadError
from idm.core.events import DownloadEvent
from idm.core.http import DEFAULT_USER_AGENT, probe_url
from idm.core.segment import SegmentControl, download_segment
from idm.core.speed_limiter import ChainedSpeedLimiter, SpeedLimiter
from idm.storage.models import DownloadRecord, DownloadStatus, SegmentRecord
from idm.storage.repository import DownloadRepository

CHECKPOINT_INTERVAL = 1.0  # seconds between DB persist + progress event


def plan_segments(download_id: int, total_size: int, connections: int) -> list[SegmentRecord]:
    """Split [0, total_size) into up to `connections` contiguous byte ranges."""
    if total_size <= 0:
        return [SegmentRecord(id=None, download_id=download_id, index=0,
                               start_byte=0, end_byte=-1)]
    connections = max(1, min(connections, total_size))
    base_size = total_size // connections
    segments: list[SegmentRecord] = []
    start = 0
    for i in range(connections):
        is_last = i == connections - 1
        end = total_size - 1 if is_last else start + base_size - 1
        segments.append(SegmentRecord(
            id=None, download_id=download_id, index=i,
            start_byte=start, end_byte=end,
        ))
        start = end + 1
    return segments


class DownloadTask:
    """Owns the lifecycle of a single download: probe, segment, run, persist.

    Engine-only, no GUI dependency. `on_event` is called from arbitrary
    threads (a background checkpoint thread, or the calling thread for
    terminal transitions) — consumers must be thread-safe.
    """

    def __init__(
        self,
        record: DownloadRecord,
        repository: DownloadRepository,
        on_event: Callable[[DownloadEvent], None],
        global_limiter: SpeedLimiter | None = None,
        session_factory: Callable[[], requests.Session] = requests.Session,
    ):
        self.record = record
        self._repo = repository
        self._on_event = on_event
        self._global_limiter = global_limiter or SpeedLimiter(None)
        self._own_limiter = SpeedLimiter(record.speed_limit_bytes)
        self._session_factory = session_factory

        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._executor: ThreadPoolExecutor | None = None
        self._futures: list[Future] = []
        self._checkpoint_thread: threading.Thread | None = None
        self._stop_checkpoint = threading.Event()
        self._run_lock = threading.Lock()
        self._last_checkpoint_bytes = 0
        self._last_checkpoint_time = time.monotonic()

    # -- public control ------------------------------------------------

    def start(self) -> None:
        with self._run_lock:
            self._pause_event.clear()
            self._cancel_event.clear()
            session = self._session_factory()

            try:
                if self.record.total_size < 0 or not self.record.segments:
                    self._probe_and_plan(session)
                self._allocate_file()
            except (UnrecoverableDownloadError, OSError) as exc:
                self._set_status(DownloadStatus.FAILED, error_message=str(exc))
                return

            self._launch_segment_threads(session)
            self._set_status(DownloadStatus.DOWNLOADING)
            self._start_checkpoint_thread()

    def pause(self) -> None:
        self._pause_event.set()
        self._join_workers()
        self._checkpoint(final=True)
        self._set_status(DownloadStatus.PAUSED)

    def cancel(self) -> None:
        self._cancel_event.set()
        self._join_workers()
        self._set_status(DownloadStatus.CANCELED)
        try:
            if os.path.exists(self.record.destination_path):
                os.remove(self.record.destination_path)
        except OSError:
            pass
        self._repo.replace_segments(self.record.id, [])
        self.record.segments = []
        self.record.downloaded_bytes = 0

    def resume(self) -> None:
        self.start()

    def retry(self) -> None:
        self._repo.increment_retry(self.record.id)
        self.record.retry_count += 1
        self.start()

    def set_speed_limit(self, bytes_per_sec: int | None) -> None:
        self._own_limiter.set_rate(bytes_per_sec)
        self.record.speed_limit_bytes = bytes_per_sec

    def is_running(self) -> bool:
        return bool(self._futures) and any(not f.done() for f in self._futures)

    # -- setup -----------------------------------------------------------

    def _probe_and_plan(self, session: requests.Session) -> None:
        try:
            probe = probe_url(self.record.url, session=session)
        except requests.exceptions.RequestException as exc:
            raise UnrecoverableDownloadError(f"probe failed: {exc}") from exc

        self.record.total_size = probe.total_size
        self.record.supports_ranges = probe.supports_ranges
        self._repo.update_total_size(self.record.id, probe.total_size, probe.supports_ranges)

        connections = self.record.connections if probe.supports_ranges else 1
        segments = plan_segments(self.record.id, probe.total_size, connections)
        self._repo.replace_segments(self.record.id, segments)
        for seg in segments:
            seg.id = self._find_segment_id(seg.index)
        self.record.segments = segments

    def _find_segment_id(self, index: int) -> int:
        for seg in self._repo.get_segments(self.record.id):
            if seg.index == index:
                return seg.id
        raise RuntimeError("segment not found after insert")

    def _allocate_file(self) -> None:
        path = self.record.destination_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, "wb") as fh:
                if self.record.total_size > 0:
                    fh.seek(self.record.total_size - 1)
                    fh.write(b"\0")

    def _launch_segment_threads(self, session: requests.Session) -> None:
        control = SegmentControl(self._pause_event, self._cancel_event)
        connections = max(1, len(self.record.segments))
        self._executor = ThreadPoolExecutor(max_workers=connections)
        self._futures = []
        for seg in self.record.segments:
            if seg.is_complete:
                continue
            future = self._executor.submit(
                download_segment,
                session, self.record.url, seg, self.record.destination_path,
                control, self._segment_speed_limiter(),
                self._on_segment_progress,
                use_range=self.record.supports_ranges and not seg.size_unknown,
            )
            self._futures.append(future)

    def _segment_speed_limiter(self) -> ChainedSpeedLimiter:
        # Each chunk write is throttled by both this download's own cap and
        # the queue-wide global cap (shared SpeedLimiter instance injected
        # by DownloadManager), so either limit is respected independently.
        return ChainedSpeedLimiter(self._own_limiter, self._global_limiter)

    # -- progress ----------------------------------------------------------

    def _on_segment_progress(self, segment_id: int, downloaded_bytes: int) -> None:
        # Segment byte counts are mutated in place on the shared SegmentRecord
        # objects; the checkpoint thread polls them periodically. Nothing to
        # do here for now — kept as an extension point (e.g. per-segment UI).
        pass

    def _start_checkpoint_thread(self) -> None:
        self._stop_checkpoint.clear()
        self._last_checkpoint_bytes = self._total_downloaded()
        self._last_checkpoint_time = time.monotonic()

        def _loop():
            while not self._stop_checkpoint.is_set():
                if self._stop_checkpoint.wait(CHECKPOINT_INTERVAL):
                    break
                if not self.is_running():
                    break
                self._checkpoint(final=False)
            self._finalize_if_done()

        self._checkpoint_thread = threading.Thread(
            target=_loop, name=f"idm-checkpoint-{self.record.id}", daemon=True
        )
        self._checkpoint_thread.start()

    def _total_downloaded(self) -> int:
        return sum(s.downloaded_bytes for s in self.record.segments)

    def _checkpoint(self, final: bool) -> None:
        for seg in self.record.segments:
            self._repo.update_segment_progress(seg.id, seg.downloaded_bytes)
        total = self._total_downloaded()
        self._repo.update_progress(self.record.id, total)
        self.record.downloaded_bytes = total

        now = time.monotonic()
        elapsed = max(1e-6, now - self._last_checkpoint_time)
        speed = (total - self._last_checkpoint_bytes) / elapsed
        self._last_checkpoint_bytes = total
        self._last_checkpoint_time = now

        eta = None
        if speed > 0 and self.record.total_size > 0:
            eta = max(0.0, (self.record.total_size - total) / speed)

        status = self._current_status()
        self._on_event(DownloadEvent(
            download_id=self.record.id, status=status,
            downloaded_bytes=total, total_size=self.record.total_size,
            speed_bytes_per_sec=max(0.0, speed), eta_seconds=eta,
        ))

    def _current_status(self) -> DownloadStatus:
        if self._cancel_event.is_set():
            return DownloadStatus.CANCELED
        if self._pause_event.is_set():
            return DownloadStatus.PAUSED
        return DownloadStatus.DOWNLOADING

    def _finalize_if_done(self) -> None:
        if self._pause_event.is_set() or self._cancel_event.is_set():
            return
        errors = self._collect_errors()
        if errors:
            self._checkpoint(final=True)
            message = "; ".join(str(e) for e in errors)
            self._set_status(DownloadStatus.FAILED, error_message=message)
            return

        self._checkpoint(final=True)
        # No errors and we weren't paused/canceled: every segment future
        # returned normally, which download_segment only does on completion.
        self._set_status(DownloadStatus.COMPLETED)

    def _collect_errors(self) -> list[BaseException]:
        errors = []
        for f in self._futures:
            exc = f.exception()
            if exc is not None:
                errors.append(exc)
        return errors

    def _join_workers(self) -> None:
        self._stop_checkpoint.set()
        if self._executor:
            for f in self._futures:
                try:
                    f.result()
                except Exception:
                    pass  # surfaced later via _collect_errors()
            self._executor.shutdown(wait=True)
            self._executor = None
        if self._checkpoint_thread and self._checkpoint_thread.is_alive():
            self._checkpoint_thread.join(timeout=5)

    def _set_status(self, status: DownloadStatus, error_message: str | None = None) -> None:
        self.record.status = status
        self._repo.update_status(self.record.id, status, error_message)
        self._on_event(DownloadEvent(
            download_id=self.record.id, status=status,
            downloaded_bytes=self.record.downloaded_bytes,
            total_size=self.record.total_size,
            error_message=error_message,
        ))
