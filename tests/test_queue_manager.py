import threading
import time

import pytest

from idm.core.errors import DuplicateDownloadError
from idm.core.events import DownloadEvent
from idm.core.queue_manager import DownloadManager
from idm.storage.db import Database
from idm.storage.models import DownloadStatus
from idm.storage.repository import DownloadRepository

URL = "https://example.com/testfile.bin"


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    yield DownloadRepository(db)
    db.close()


def _wait_until(predicate, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class _FakeTask:
    """Controllable stand-in for DownloadTask so DownloadManager's dispatch
    policy (concurrency cap, priority order, pause freeing a slot) can be
    tested deterministically -- without racing real HTTP/thread timing.
    Blocks in start() until release() is called, then reports COMPLETED.
    """

    def __init__(self, record, repository, on_event, **_kwargs):
        self.record = record
        self._repo = repository
        self._on_event = on_event
        self._release_event = threading.Event()
        self._paused = False

    def start(self) -> None:
        self._repo.update_status(self.record.id, DownloadStatus.DOWNLOADING)
        self._emit(DownloadStatus.DOWNLOADING)
        self._release_event.wait()
        if self._paused:
            return
        self._repo.update_status(self.record.id, DownloadStatus.COMPLETED)
        self._emit(DownloadStatus.COMPLETED)

    def pause(self) -> None:
        self._paused = True
        self._repo.update_status(self.record.id, DownloadStatus.PAUSED)
        self._release_event.set()
        self._emit(DownloadStatus.PAUSED)

    def cancel(self) -> None:
        self._paused = True
        self._repo.update_status(self.record.id, DownloadStatus.CANCELED)
        self._release_event.set()
        self._emit(DownloadStatus.CANCELED)

    def is_running(self) -> bool:
        return not self._release_event.is_set()

    def release(self) -> None:
        self._release_event.set()

    def _emit(self, status: DownloadStatus) -> None:
        self._on_event(DownloadEvent(
            download_id=self.record.id, status=status,
            downloaded_bytes=0, total_size=0,
        ))


def _fake_task_factory(tasks: dict):
    def factory(record, repository, on_event, **kwargs):
        task = _FakeTask(record, repository, on_event, **kwargs)
        tasks[record.id] = task
        return task
    return factory


def test_add_download_creates_queued_record(tmp_path, repo):
    manager = DownloadManager(repo, downloads_root=tmp_path, max_concurrent=3)
    record = manager.add_download(
        "https://example.com/report.pdf", filename="report.pdf",
        start_immediately=False,
    )
    fetched = repo.get_download(record.id)
    assert fetched.status == DownloadStatus.QUEUED
    assert fetched.category == "Documents"
    assert fetched.filename == "report.pdf"


def test_scheduled_download_is_not_queued_yet(tmp_path, repo):
    manager = DownloadManager(repo, downloads_root=tmp_path, max_concurrent=3)
    record = manager.add_download(
        "https://example.com/report.pdf", filename="report.pdf",
        scheduled_at="2099-01-01T00:00:00+00:00",
    )
    assert repo.get_download(record.id).status == DownloadStatus.SCHEDULED


def test_add_download_rejects_duplicate_url_while_active(tmp_path, repo):
    manager = DownloadManager(repo, downloads_root=tmp_path, max_concurrent=3)
    first = manager.add_download(URL, filename="file.bin", start_immediately=False)

    with pytest.raises(DuplicateDownloadError) as excinfo:
        manager.add_download(URL, filename="file.bin", start_immediately=False)

    assert excinfo.value.existing.id == first.id
    # Only one row for this URL/destination should exist -- the rejected
    # call must not have inserted a second DB record before raising.
    assert len(repo.list_downloads()) == 1


def test_add_download_rejects_duplicate_destination_even_with_different_url(tmp_path, repo):
    # Two different URLs that happen to resolve to the same filename in the
    # same folder are just as dangerous as a literal duplicate URL: both
    # DownloadTasks would write to the same file concurrently.
    manager = DownloadManager(repo, downloads_root=tmp_path, max_concurrent=3)
    first = manager.add_download(
        "https://mirror-a.example.com/file.bin", filename="file.bin",
        start_immediately=False,
    )
    with pytest.raises(DuplicateDownloadError) as excinfo:
        manager.add_download(
            "https://mirror-b.example.com/file.bin", filename="file.bin",
            start_immediately=False,
        )
    assert excinfo.value.existing.id == first.id


def test_add_download_allows_resubmitting_after_previous_copy_finished(tmp_path, repo):
    tasks: dict = {}
    manager = DownloadManager(
        repo, downloads_root=tmp_path, max_concurrent=3,
        task_factory=_fake_task_factory(tasks),
    )
    first = manager.add_download(URL, filename="file.bin")
    assert _wait_until(lambda: repo.get_download(first.id).status == DownloadStatus.DOWNLOADING)

    tasks[first.id].release()
    assert _wait_until(lambda: repo.get_download(first.id).status == DownloadStatus.COMPLETED)

    # The slot is free now (terminal status) -- re-adding the same URL must
    # succeed rather than being treated as still-active.
    second = manager.add_download(URL, filename="file.bin", start_immediately=False)
    assert second.id != first.id


def test_max_concurrent_caps_active_dispatch(tmp_path, repo):
    tasks: dict = {}
    manager = DownloadManager(
        repo, downloads_root=tmp_path, max_concurrent=2,
        task_factory=_fake_task_factory(tasks),
    )
    records = [
        manager.add_download(f"https://example.com/file{i}.bin", filename=f"file{i}.bin")
        for i in range(4)
    ]

    assert _wait_until(lambda: len(manager._tasks) == 2)
    time.sleep(0.1)  # give a moment for any over-dispatch bug to manifest
    assert len(manager._tasks) == 2

    statuses = [repo.get_download(r.id).status for r in records]
    assert statuses.count(DownloadStatus.QUEUED) == 2
    assert statuses.count(DownloadStatus.DOWNLOADING) == 2

    # Keep releasing whichever fake tasks are currently blocking a slot --
    # as each completes, the dispatcher should backfill from the queue.
    def release_until_all_complete():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for task in list(tasks.values()):
                task.release()
            if all(
                repo.get_download(r.id).status == DownloadStatus.COMPLETED
                for r in records
            ):
                return True
            time.sleep(0.02)
        return False

    assert release_until_all_complete(), [
        repo.get_download(r.id).status for r in records
    ]


def test_pause_frees_a_concurrency_slot_for_the_next_queued_download(tmp_path, repo):
    tasks: dict = {}
    manager = DownloadManager(
        repo, downloads_root=tmp_path, max_concurrent=1,
        task_factory=_fake_task_factory(tasks),
    )
    first = manager.add_download("https://example.com/first.bin", filename="first.bin")
    second = manager.add_download("https://example.com/second.bin", filename="second.bin")

    assert _wait_until(lambda: len(manager._tasks) == 1)
    assert repo.get_download(second.id).status == DownloadStatus.QUEUED

    manager.pause(first.id)
    assert repo.get_download(first.id).status == DownloadStatus.PAUSED

    # pausing the first must free the slot for the second to launch
    assert _wait_until(
        lambda: repo.get_download(second.id).status == DownloadStatus.DOWNLOADING
    )

    tasks[second.id].release()
    assert _wait_until(
        lambda: repo.get_download(second.id).status == DownloadStatus.COMPLETED
    )


def test_pause_resume_cancel_emit_events_for_a_download_with_no_running_task(tmp_path, repo):
    # Regression test: pause/resume/cancel on a download that was never
    # dispatched (max_concurrent=0 means _tasks never gets an entry for it)
    # used to update the DB directly without emitting a DownloadEvent, so
    # the GUI's table model -- which only redraws on those events -- never
    # found out the status had changed.
    manager = DownloadManager(repo, downloads_root=tmp_path, max_concurrent=0)
    events: list[DownloadEvent] = []
    manager.add_listener(events.append)

    record = manager.add_download("https://example.com/file.bin", filename="file.bin")
    assert repo.get_download(record.id).status == DownloadStatus.QUEUED

    manager.pause(record.id)
    assert repo.get_download(record.id).status == DownloadStatus.PAUSED
    assert events and events[-1].status == DownloadStatus.PAUSED
    assert events[-1].download_id == record.id

    manager.resume(record.id)
    assert repo.get_download(record.id).status == DownloadStatus.QUEUED
    assert events[-1].status == DownloadStatus.QUEUED

    manager.cancel(record.id)
    assert repo.get_download(record.id).status == DownloadStatus.CANCELED
    assert events[-1].status == DownloadStatus.CANCELED


def test_priority_ordering_dispatches_higher_priority_first(tmp_path, repo):
    tasks: dict = {}
    manager = DownloadManager(
        repo, downloads_root=tmp_path, max_concurrent=1,
        task_factory=_fake_task_factory(tasks),
    )
    low = manager.add_download("https://example.com/low.bin", filename="low.bin", start_immediately=False)
    high = manager.add_download("https://example.com/high.bin", filename="high.bin", start_immediately=False)
    # Set priorities directly via the repository, not manager.set_priority(),
    # which would itself trigger a dispatch after only the first call and
    # launch "low" (equal priority, earlier created_at) before "high" is
    # ever re-prioritized.
    repo.set_priority(low.id, 0)
    repo.set_priority(high.id, 10)

    manager.start_queue()
    assert _wait_until(lambda: len(manager._tasks) == 1)
    assert repo.get_download(high.id).status == DownloadStatus.DOWNLOADING
    assert repo.get_download(low.id).status == DownloadStatus.QUEUED


def test_remove_deletes_record(tmp_path, repo):
    manager = DownloadManager(repo, downloads_root=tmp_path, max_concurrent=3)
    record = manager.add_download(
        "https://example.com/report.pdf", filename="report.pdf",
        start_immediately=False,
    )
    manager.remove(record.id)
    assert repo.get_download(record.id) is None
