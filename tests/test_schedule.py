from datetime import datetime, time

import pytest

from idm.core.schedule import QueueScheduler, ScheduleConfig, window_open
from idm.storage.db import Database
from idm.storage.models import DownloadRecord, DownloadStatus
from idm.storage.repository import DownloadRepository

# 2026-10-12 is a Monday
MON, TUE, WED, SAT = (datetime(2026, 10, d) for d in (12, 13, 14, 17))


def at(day: datetime, h: int, m: int = 0) -> datetime:
    return day.replace(hour=h, minute=m)


def test_same_day_window():
    cfg = ScheduleConfig(enabled=True, start=time(9), stop=time(17), days=(0,))
    assert window_open(cfg, at(MON, 9))
    assert window_open(cfg, at(MON, 16, 59))
    assert not window_open(cfg, at(MON, 17))
    assert not window_open(cfg, at(TUE, 10))  # Tuesday is not selected


def test_overnight_window_belongs_to_the_day_it_started():
    cfg = ScheduleConfig(enabled=True, start=time(23), stop=time(6), days=(0,))  # Mondays only
    assert window_open(cfg, at(MON, 23, 30))
    assert window_open(cfg, at(TUE, 2))  # still Monday's window
    assert not window_open(cfg, at(MON, 2))  # Sunday's window, not selected
    assert not window_open(cfg, at(TUE, 23, 30))
    assert not window_open(cfg, at(TUE, 12))


def test_settings_roundtrip_and_garbage_falls_back():
    values = {"schedule_enabled": "1", "schedule_start": "22:15", "schedule_stop": "bad",
              "schedule_days": "5,6,x,9", "schedule_finish": "explode"}
    cfg = ScheduleConfig.from_settings(lambda k, d=None: values.get(k, d))
    assert cfg.enabled and cfg.start == time(22, 15) and cfg.stop == time(6)
    assert cfg.days == (5, 6)
    assert cfg.finish_action == "nothing"


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "s.sqlite3")
    yield DownloadRepository(db)
    db.close()


def _add(repo, status):
    rec = DownloadRecord(id=None, url="u", filename="f", destination_path="p", category="Other",
                         total_size=-1, status=status)
    rec.id = repo.create_download(rec)
    return rec


def _scheduler(repo, cfg, clock, log):
    return QueueScheduler(
        repo=repo, get_config=lambda: cfg,
        start_queue=lambda: log.append("start"), stop_queue=lambda: log.append("stop"),
        pause_active=lambda: log.append("pause"), on_finished=lambda a: log.append(f"finish:{a}"),
        now=lambda: clock[0],
    )


def test_queue_opens_and_closes_with_the_window(repo):
    cfg = ScheduleConfig(enabled=True, start=time(9), stop=time(17), days=(0,))
    clock, log = [at(MON, 8)], []
    s = _scheduler(repo, cfg, clock, log)
    s.tick()
    assert log == ["stop"]  # closed at startup: hold the queue
    clock[0] = at(MON, 9, 1)
    s.tick()
    assert log == ["stop", "start"]
    s.tick()  # still open: nothing new
    assert log == ["stop", "start"]
    clock[0] = at(MON, 17, 1)
    s.tick()
    assert log[-2:] == ["stop", "pause"]


def test_finish_action_fires_once_after_the_work_is_done(repo):
    cfg = ScheduleConfig(enabled=True, start=time(9), stop=time(17), days=(0,), finish_action="shutdown")
    clock, log = [at(MON, 10)], []
    s = _scheduler(repo, cfg, clock, log)
    job = _add(repo, DownloadStatus.DOWNLOADING)
    s.tick()
    assert "finish:shutdown" not in log
    repo.update_status(job.id, DownloadStatus.COMPLETED)
    s.tick()
    s.tick()
    assert log.count("finish:shutdown") == 1


def test_no_finish_action_when_nothing_was_ever_pending(repo):
    cfg = ScheduleConfig(enabled=True, start=time(9), stop=time(17), days=(0,), finish_action="exit")
    clock, log = [at(MON, 10)], []
    s = _scheduler(repo, cfg, clock, log)
    s.tick()
    s.tick()
    assert not any(e.startswith("finish") for e in log)


def test_disabled_schedule_does_nothing(repo):
    cfg = ScheduleConfig(enabled=False)
    clock, log = [at(MON, 10)], []
    _scheduler(repo, cfg, clock, log).tick()
    assert log == []
