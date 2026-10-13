import pytest

from idm.storage.db import Database
from idm.storage.models import DownloadRecord, DownloadStatus, SegmentRecord
from idm.storage.repository import DownloadRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    yield DownloadRepository(db)
    db.close()


def _new_record(**overrides) -> DownloadRecord:
    defaults = dict(
        id=None, url="https://example.com/file.zip", filename="file.zip",
        destination_path="/tmp/file.zip", category="Compressed",
        total_size=1000, status=DownloadStatus.QUEUED,
    )
    defaults.update(overrides)
    return DownloadRecord(**defaults)


def test_create_and_get_download(repo):
    record = _new_record()
    download_id = repo.create_download(record)
    fetched = repo.get_download(download_id)
    assert fetched.url == "https://example.com/file.zip"
    assert fetched.status == DownloadStatus.QUEUED
    assert fetched.segments == []


def test_segments_persist_and_reload(repo):
    record = _new_record()
    download_id = repo.create_download(record)
    segments = [
        SegmentRecord(id=None, download_id=download_id, index=0, start_byte=0, end_byte=499),
        SegmentRecord(id=None, download_id=download_id, index=1, start_byte=500, end_byte=999),
    ]
    repo.replace_segments(download_id, segments)

    reloaded = repo.get_segments(download_id)
    assert len(reloaded) == 2
    assert reloaded[0].start_byte == 0 and reloaded[0].end_byte == 499
    assert reloaded[1].start_byte == 500 and reloaded[1].end_byte == 999


def test_segment_progress_survives_reload_for_resume(repo):
    record = _new_record()
    download_id = repo.create_download(record)
    repo.replace_segments(download_id, [
        SegmentRecord(id=None, download_id=download_id, index=0, start_byte=0, end_byte=999),
    ])
    seg = repo.get_segments(download_id)[0]
    repo.update_segment_progress(seg.id, 400)

    reloaded = repo.get_segments(download_id)[0]
    assert reloaded.downloaded_bytes == 400
    assert reloaded.remaining_bytes == 600


def test_update_status_sets_completed_at_only_on_completed(repo):
    download_id = repo.create_download(_new_record())
    repo.update_status(download_id, DownloadStatus.DOWNLOADING)
    assert repo.get_download(download_id).completed_at is None

    repo.update_status(download_id, DownloadStatus.COMPLETED)
    assert repo.get_download(download_id).completed_at is not None


def test_list_downloads_filters_by_status(repo):
    id_a = repo.create_download(_new_record(status=DownloadStatus.QUEUED))
    id_b = repo.create_download(_new_record(status=DownloadStatus.QUEUED))
    repo.update_status(id_b, DownloadStatus.COMPLETED)

    queued = repo.list_downloads([DownloadStatus.QUEUED])
    assert [d.id for d in queued] == [id_a]

    completed = repo.list_downloads([DownloadStatus.COMPLETED])
    assert [d.id for d in completed] == [id_b]


def test_list_downloads_orders_by_priority_then_created(repo):
    id_low = repo.create_download(_new_record(priority=0))
    id_high = repo.create_download(_new_record(priority=10))
    ordered = repo.list_downloads()
    assert ordered[0].id == id_high
    assert ordered[1].id == id_low


def test_delete_download_cascades_segments(repo):
    download_id = repo.create_download(_new_record())
    repo.replace_segments(download_id, [
        SegmentRecord(id=None, download_id=download_id, index=0, start_byte=0, end_byte=999),
    ])
    repo.delete_download(download_id)
    assert repo.get_download(download_id) is None
    assert repo.get_segments(download_id) == []


def test_settings_roundtrip(repo):
    assert repo.get_setting("max_concurrent") is None
    assert repo.get_setting("max_concurrent", "3") == "3"
    repo.set_setting("max_concurrent", "5")
    assert repo.get_setting("max_concurrent") == "5"
    repo.set_setting("max_concurrent", "7")  # upsert path
    assert repo.get_setting("max_concurrent") == "7"
