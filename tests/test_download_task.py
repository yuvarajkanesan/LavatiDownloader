import threading
import time

import pytest
import responses

from idm.core.task import DownloadTask
from idm.storage.db import Database
from idm.storage.models import DownloadRecord, DownloadStatus, SegmentRecord
from idm.storage.repository import DownloadRepository

from .conftest import FILE_CONTENT, range_serving_callback

URL = "https://example.com/testfile.bin"


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    yield DownloadRepository(db)
    db.close()


def _wait_for_terminal(repo, download_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = repo.get_download(download_id)
        if record.status in (
            DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELED,
        ):
            return record
        time.sleep(0.05)
    raise TimeoutError("download did not reach a terminal state in time")


@responses.activate
def test_segmented_download_completes_with_correct_content(tmp_path, repo):
    responses.add_callback(responses.HEAD, URL, callback=range_serving_callback())
    responses.add_callback(responses.GET, URL, callback=range_serving_callback())

    dest = tmp_path / "out" / "testfile.bin"
    record = DownloadRecord(
        id=None, url=URL, filename="testfile.bin", destination_path=str(dest),
        category="Other", total_size=-1, status=DownloadStatus.QUEUED, connections=4,
    )
    record.id = repo.create_download(record)

    task = DownloadTask(record, repo, on_event=lambda e: None)
    task.start()

    final = _wait_for_terminal(repo, record.id)
    assert final.status == DownloadStatus.COMPLETED, final.error_message
    assert dest.read_bytes() == FILE_CONTENT
    assert len(final.segments) == 4
    assert final.downloaded_bytes == len(FILE_CONTENT)


@responses.activate
def test_resume_requests_only_the_remaining_byte_range(tmp_path, repo):
    get_ranges = []
    callback = range_serving_callback(
        on_get=lambda req: get_ranges.append(req.headers.get("Range"))
    )
    responses.add_callback(responses.HEAD, URL, callback=callback)
    responses.add_callback(responses.GET, URL, callback=callback)

    dest = tmp_path / "out" / "testfile.bin"
    dest.parent.mkdir(parents=True)
    already_downloaded = 2000
    with open(dest, "wb") as fh:
        # Simulate a prior run that got this far: real bytes up to the
        # checkpoint, untouched (pre-allocated) space after it.
        fh.write(FILE_CONTENT[:already_downloaded])
        fh.write(b"\0" * (len(FILE_CONTENT) - already_downloaded))

    record = DownloadRecord(
        id=None, url=URL, filename="testfile.bin", destination_path=str(dest),
        category="Other", total_size=len(FILE_CONTENT), status=DownloadStatus.QUEUED,
        connections=1, supports_ranges=True,
    )
    record.id = repo.create_download(record)
    repo.replace_segments(record.id, [
        SegmentRecord(
            id=None, download_id=record.id, index=0,
            start_byte=0, end_byte=len(FILE_CONTENT) - 1,
            downloaded_bytes=already_downloaded,
        ),
    ])
    record.segments = repo.get_segments(record.id)

    task = DownloadTask(record, repo, on_event=lambda e: None)
    task.start()

    final = _wait_for_terminal(repo, record.id)
    assert final.status == DownloadStatus.COMPLETED, final.error_message
    assert dest.read_bytes() == FILE_CONTENT

    expected_range = f"bytes={already_downloaded}-{len(FILE_CONTENT) - 1}"
    assert expected_range in get_ranges, get_ranges


@responses.activate
def test_no_range_support_falls_back_to_single_connection(tmp_path, repo):
    def callback(request):
        headers = {"Content-Type": "application/octet-stream"}
        if request.method == "HEAD":
            headers["Content-Length"] = str(len(FILE_CONTENT))
            return (200, headers, b"")
        headers["Content-Length"] = str(len(FILE_CONTENT))
        return (200, headers, FILE_CONTENT)

    responses.add_callback(responses.HEAD, URL, callback=callback)
    responses.add_callback(responses.GET, URL, callback=callback)

    dest = tmp_path / "out" / "testfile.bin"
    record = DownloadRecord(
        id=None, url=URL, filename="testfile.bin", destination_path=str(dest),
        category="Other", total_size=-1, status=DownloadStatus.QUEUED, connections=8,
    )
    record.id = repo.create_download(record)

    task = DownloadTask(record, repo, on_event=lambda e: None)
    task.start()

    final = _wait_for_terminal(repo, record.id)
    assert final.status == DownloadStatus.COMPLETED, final.error_message
    assert dest.read_bytes() == FILE_CONTENT
    assert len(final.segments) == 1
    assert final.supports_ranges is False


@responses.activate
def test_cancel_deletes_partial_file_and_clears_segments(tmp_path, repo):
    # The mocked GET blocks until released, simulating a segment thread
    # stuck mid-request (i.e. inside session.get(), not the chunk loop) --
    # cancel() must still be able to tear the task down once the request
    # eventually returns.
    release = threading.Event()

    def slow_callback(request):
        if request.method == "GET":
            release.wait(timeout=5)
        return range_serving_callback()(request)

    responses.add_callback(responses.HEAD, URL, callback=range_serving_callback())
    responses.add_callback(responses.GET, URL, callback=slow_callback)

    dest = tmp_path / "out" / "testfile.bin"
    record = DownloadRecord(
        id=None, url=URL, filename="testfile.bin", destination_path=str(dest),
        category="Other", total_size=-1, status=DownloadStatus.QUEUED, connections=1,
    )
    record.id = repo.create_download(record)

    task = DownloadTask(record, repo, on_event=lambda e: None)
    task.start()
    time.sleep(0.2)  # let the segment thread get into the blocked GET

    canceller = threading.Thread(target=task.cancel)
    canceller.start()
    time.sleep(0.1)
    release.set()  # unblock the in-flight request so cancel() can finish joining
    canceller.join(timeout=5)
    assert not canceller.is_alive()

    assert not dest.exists()
    final = repo.get_download(record.id)
    assert final.status == DownloadStatus.CANCELED
    assert final.segments == []
