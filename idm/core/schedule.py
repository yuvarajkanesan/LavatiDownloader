"""Recurring queue schedule: run the queue between a start and stop time on chosen days, then optionally exit,
sleep or shut down. Pure logic plus a small controller; the GUI only feeds it settings and a clock.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Callable

from idm.storage.models import DownloadStatus
from idm.storage.repository import DownloadRepository

FINISH_ACTIONS = ("nothing", "exit", "sleep", "shutdown")
ALL_DAYS = (0, 1, 2, 3, 4, 5, 6)  # Monday = 0, like datetime.weekday()
POLL_SECONDS = 20.0


def parse_hhmm(text: str, default: time) -> time:
    try:
        hours, minutes = text.strip().split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return default


@dataclass
class ScheduleConfig:
    enabled: bool = False
    start: time = time(23, 0)
    stop: time = time(6, 0)
    days: tuple[int, ...] = (0, 1, 2, 3, 4)
    finish_action: str = "nothing"

    @classmethod
    def from_settings(cls, get) -> "ScheduleConfig":
        """`get(key, default)` is DownloadRepository.get_setting."""
        days = tuple(sorted({int(d) for d in str(get("schedule_days", "0,1,2,3,4")).split(",") if d.strip().isdigit()
                             and 0 <= int(d) <= 6}))
        action = get("schedule_finish", "nothing")
        return cls(
            enabled=get("schedule_enabled", "0") == "1",
            start=parse_hhmm(get("schedule_start", "23:00"), time(23, 0)),
            stop=parse_hhmm(get("schedule_stop", "06:00"), time(6, 0)),
            days=days,
            finish_action=action if action in FINISH_ACTIONS else "nothing",
        )


def window_open(cfg: ScheduleConfig, now: datetime) -> bool:
    """Is `now` inside the run window? An overnight window (stop <= start) belongs to the day it started on."""
    t = now.time()
    if cfg.start == cfg.stop:
        return now.weekday() in cfg.days  # a full-day window
    if cfg.start < cfg.stop:
        return cfg.start <= t < cfg.stop and now.weekday() in cfg.days
    if t >= cfg.start:
        return now.weekday() in cfg.days
    if t < cfg.stop:
        return (now - timedelta(days=1)).weekday() in cfg.days
    return False


def perform_finish_action(action: str) -> None:
    """Sleep or shut the PC down. 'exit' is handled by the GUI. Shutdown waits 60 s so it can be aborted."""
    if sys.platform != "win32":
        return
    if action == "sleep":
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    elif action == "shutdown":
        subprocess.Popen(["shutdown", "/s", "/t", "60", "/c", "Lavati Downloader finished its scheduled downloads."])


@dataclass
class QueueScheduler:
    """Opens and closes the queue as the window opens and closes, and fires the finish action once the downloads
    started by a window are all done. Call tick() periodically (start()/stop() run a background thread)."""

    repo: DownloadRepository
    get_config: Callable[[], ScheduleConfig]
    start_queue: Callable[[], None]
    stop_queue: Callable[[], None]
    pause_active: Callable[[], None]
    on_finished: Callable[[str], None]
    now: Callable[[], datetime] = datetime.now
    _was_open: bool | None = field(default=None, init=False)
    _had_work: bool = field(default=False, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def _pending(self) -> int:
        return len(self.repo.list_downloads([DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING]))

    def tick(self) -> None:
        cfg = self.get_config()
        if not cfg.enabled:
            self._was_open = None
            self._had_work = False
            return
        is_open = window_open(cfg, self.now())
        if is_open and self._was_open is not True:
            self._had_work = False
            self.start_queue()
        elif not is_open and self._was_open is True:
            self.stop_queue()
            self.pause_active()
            self._had_work = False
        elif self._was_open is None and not is_open:
            # first look at a closed window (app just started or the schedule was just enabled)
            self.stop_queue()
        self._was_open = is_open
        if not is_open:
            return
        pending = self._pending()
        if pending:
            self._had_work = True
        elif self._had_work:
            self._had_work = False
            if cfg.finish_action != "nothing":
                self.on_finished(cfg.finish_action)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="idm-queue-schedule", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - a bad tick must not kill the schedule
                pass
            if self._stop_event.wait(POLL_SECONDS):
                return
