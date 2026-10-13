"""A DownloadTask look-alike that fetches video/social links with yt-dlp.

The queue manager treats it like any other task (start / pause / cancel / events). yt-dlp itself downloads with
several fragments in parallel and keeps `.part` files, so pausing and resuming continues where it stopped.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Callable

from idm.core.events import DownloadEvent
from idm.core.speed_limiter import SpeedLimiter
from idm.core.video import VideoOptions, build_ydl_options
from idm.storage.models import DownloadRecord, DownloadStatus
from idm.storage.paths import category_for_extension
from idm.storage.repository import DownloadRepository


class _Interrupted(Exception):
    """Raised from yt-dlp's progress hook to stop a pause or cancel quickly."""


class VideoTask:
    def __init__(
        self,
        record: DownloadRecord,
        repository: DownloadRepository,
        on_event: Callable[[DownloadEvent], None],
        global_limiter: SpeedLimiter | None = None,
        ydl_factory=None,
    ):
        self.record = record
        self._repo = repository
        self._on_event = on_event
        self._global_limiter = global_limiter or SpeedLimiter(None)
        self._own_limiter = SpeedLimiter(record.speed_limit_bytes)
        self._ydl_factory = ydl_factory
        self._pause = threading.Event()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._files: dict[str, tuple[int, int]] = {}  # temp file -> (downloaded, total)
        self._last_emit = 0.0

    # -- control ---------------------------------------------------------

    def start(self) -> None:
        """Runs the whole download; DownloadManager calls this on its own thread."""
        self._pause.clear()
        self._cancel.clear()
        self._thread = threading.current_thread()
        self._set_status(DownloadStatus.DOWNLOADING)
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001 - yt-dlp raises many types (wrapping _Interrupted too)
            if self._pause.is_set() or self._cancel.is_set() or isinstance(exc, _Interrupted):
                self._after_interrupt()
            else:
                self._set_status(DownloadStatus.FAILED, error_message=_clean(str(exc)))

    def pause(self) -> None:
        self._pause.set()

    def cancel(self) -> None:
        self._cancel.set()

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
        return self._thread is not None and self._thread.is_alive()

    # -- work --------------------------------------------------------------

    def _run(self) -> None:
        options = VideoOptions.from_json(self.record.options)
        dest_dir = os.path.dirname(self.record.destination_path)
        os.makedirs(dest_dir, exist_ok=True)
        params = build_ydl_options(options, dest_dir, self.record.connections)
        rates = [r for r in (self._own_limiter.rate_bytes_per_sec, self._global_limiter.rate_bytes_per_sec) if r]
        if rates:
            params["ratelimit"] = min(rates)
        params["progress_hooks"] = [self._on_progress]
        if self._ydl_factory is None:
            import yt_dlp
            factory = yt_dlp.YoutubeDL
        else:
            factory = self._ydl_factory
        with factory(params) as ydl:
            info = ydl.extract_info(self.record.url, download=True)
        self._finish(info, dest_dir, options)

    def _on_progress(self, d: dict) -> None:
        if self._cancel.is_set() or self._pause.is_set():
            raise _Interrupted()
        name = d.get("filename") or d.get("tmpfilename") or ""
        downloaded = int(d.get("downloaded_bytes") or 0)
        total = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
        self._files[name] = (downloaded, total or self._files.get(name, (0, 0))[1])
        done = sum(v[0] for v in self._files.values())
        size = sum(v[1] for v in self._files.values())
        self.record.downloaded_bytes = done
        self.record.total_size = max(self.record.total_size, size)
        now = time.monotonic()
        if d.get("status") == "finished" or now - self._last_emit >= 0.5:
            self._last_emit = now
            self._repo.update_progress(self.record.id, done)
            if size > 0:
                self._repo.update_total_size(self.record.id, self.record.total_size, True)
            self._on_event(DownloadEvent(
                download_id=self.record.id, status=DownloadStatus.DOWNLOADING,
                downloaded_bytes=done, total_size=self.record.total_size,
                speed_bytes_per_sec=float(d.get("speed") or 0.0), eta_seconds=d.get("eta"),
            ))

    def _finish(self, info: dict | None, dest_dir: str, options: VideoOptions) -> None:
        path = self.record.destination_path
        if info:
            if options.playlist and info.get("_type") == "playlist":
                folder = os.path.join(dest_dir, re.sub(r'[\\/:*?"<>|]', "_", info.get("title") or "Playlist"))
                path = folder if os.path.isdir(folder) else dest_dir
                name = f"{info.get('title') or 'Playlist'} ({len(info.get('entries') or [])} videos)"
                category = "Music" if options.format == "mp3" else "Video"
            else:
                downloads = info.get("requested_downloads") or []
                if downloads and downloads[0].get("filepath"):
                    path = downloads[0]["filepath"]
                name = os.path.basename(path)
                category = "Music" if options.format == "mp3" else category_for_extension(name)
            self._repo.update_file(self.record.id, name, path, category)
            self.record.filename, self.record.destination_path, self.record.category = name, path, category
        if self.record.total_size <= 0:
            self.record.total_size = self.record.downloaded_bytes
        self.record.downloaded_bytes = self.record.total_size
        self._repo.update_total_size(self.record.id, self.record.total_size, True)
        self._repo.update_progress(self.record.id, self.record.total_size)
        self._set_status(DownloadStatus.COMPLETED)

    def _after_interrupt(self) -> None:
        if self._cancel.is_set():
            for name in list(self._files):
                for leftover in (name + ".part", name + ".ytdl"):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
            self.record.downloaded_bytes = 0
            self._repo.update_progress(self.record.id, 0)
            self._set_status(DownloadStatus.CANCELED)
        else:
            self._set_status(DownloadStatus.PAUSED)

    def _set_status(self, status: DownloadStatus, error_message: str | None = None) -> None:
        self.record.status = status
        self._repo.update_status(self.record.id, status, error_message)
        self._on_event(DownloadEvent(
            download_id=self.record.id, status=status,
            downloaded_bytes=self.record.downloaded_bytes, total_size=self.record.total_size,
            error_message=error_message,
        ))


def _clean(message: str) -> str:
    """yt-dlp prefixes errors with 'ERROR: ' and may embed ANSI colors."""
    message = re.sub(r"\x1b\[[0-9;]*m", "", message)
    return message.replace("ERROR: ", "").strip()[:300]
