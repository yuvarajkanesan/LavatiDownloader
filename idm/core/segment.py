from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import requests

from idm.core.errors import SegmentDownloadError
from idm.core.http import DEFAULT_USER_AGENT
from idm.core.speed_limiter import SpeedLimiter
from idm.storage.models import SegmentRecord

CHUNK_SIZE = 64 * 1024
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 30
MAX_RETRIES = 5
BACKOFF_BASE = 1.0
BACKOFF_CAP = 30.0

RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


@dataclass(slots=True)
class SegmentControl:
    """Per-download control signals shared by all of its segment threads."""

    pause_event: threading.Event
    cancel_event: threading.Event


def _backoff_delay(attempt: int) -> float:
    return min(BACKOFF_CAP, BACKOFF_BASE * (2 ** attempt))


def download_segment(
    session: requests.Session,
    url: str,
    segment: SegmentRecord,
    file_path: str,
    control: SegmentControl,
    speed_limiter: SpeedLimiter,
    on_progress: "callable[[int, int], None]",
    chunk_size: int = CHUNK_SIZE,
    max_retries: int = MAX_RETRIES,
    use_range: bool = True,
) -> None:
    """Download one byte-range of a file into its slot, respecting pause/cancel.

    `on_progress(segment_id, downloaded_bytes_for_segment)` is called after
    each chunk write with the segment's cumulative downloaded bytes so far
    (not a delta), and may be called from this thread.

    `use_range=False` is for servers without Range support (single-connection
    fallback): no Range header is sent, and any prior partial progress is
    discarded first since it can't be resumed from a known-good offset.

    Returns normally on completion, on pause, or on cancel. Raises
    SegmentDownloadError only when retries are exhausted on a real network
    failure, or when the server silently ignores a Range request (which
    would otherwise corrupt the file by writing full content at an offset).
    """
    if segment.is_complete:
        return

    if not use_range and segment.downloaded_bytes > 0:
        segment.downloaded_bytes = 0
        on_progress(segment.id, 0)

    attempt = 0
    while True:
        try:
            _run_segment(
                session, url, segment, file_path, control,
                speed_limiter, on_progress, chunk_size, use_range,
            )
            return
        except RETRYABLE_EXCEPTIONS as exc:
            if control.cancel_event.is_set() or control.pause_event.is_set():
                return
            attempt += 1
            if attempt > max_retries:
                raise SegmentDownloadError(
                    f"segment {segment.index} failed after {max_retries} retries: {exc}"
                ) from exc
            delay = _backoff_delay(attempt)
            _interruptible_sleep(delay, control)


def _interruptible_sleep(seconds: float, control: SegmentControl) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if control.cancel_event.is_set() or control.pause_event.is_set():
            return
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))


def _run_segment(
    session: requests.Session,
    url: str,
    segment: SegmentRecord,
    file_path: str,
    control: SegmentControl,
    speed_limiter: SpeedLimiter,
    on_progress,
    chunk_size: int,
    use_range: bool,
) -> None:
    range_start = segment.start_byte + segment.downloaded_bytes
    range_end = segment.end_byte
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if use_range:
        headers["Range"] = f"bytes={range_start}-{range_end}"

    with session.get(
        url, headers=headers, stream=True,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    ) as resp:
        resp.raise_for_status()
        if use_range and range_start > 0 and resp.status_code != 206:
            raise SegmentDownloadError(
                f"segment {segment.index}: server ignored Range request "
                f"(got status {resp.status_code}); refusing to write and corrupt the file"
            )
        with open(file_path, "r+b") as fh:
            fh.seek(range_start)
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if control.cancel_event.is_set() or control.pause_event.is_set():
                    return
                if not chunk:
                    continue
                speed_limiter.consume(len(chunk))
                fh.write(chunk)
                segment.downloaded_bytes += len(chunk)
                on_progress(segment.id, segment.downloaded_bytes)
                if segment.is_complete:
                    return
