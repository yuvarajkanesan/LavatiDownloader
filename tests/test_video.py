import os

import pytest

from idm.core.events import DownloadEvent
from idm.core.video import (
    VideoOptions, build_qualities, build_ydl_options, detect_site, display_name,
)
from idm.core.video_task import VideoTask
from idm.storage.db import Database
from idm.storage.models import DownloadRecord, DownloadStatus
from idm.storage.repository import DownloadRepository


@pytest.mark.parametrize("url,site", [
    ("https://www.youtube.com/watch?v=abc", "YouTube"),
    ("https://youtu.be/abc", "YouTube"),
    ("https://m.facebook.com/watch/?v=1", "Facebook"),
    ("https://www.instagram.com/reel/xyz/", "Instagram"),
    ("https://vm.tiktok.com/abc", "TikTok"),
    ("https://twitter.com/u/status/1", "X"),
    ("https://x.com/u/status/1", "X"),
    ("https://example.com/file.zip", None),
    ("https://notyoutube.com/watch", None),
    ("not a url", None),
])
def test_detect_site(url, site):
    assert detect_site(url) == site


def _fmt(height, size, vcodec="avc1", acodec="none"):
    return {"height": height, "filesize": size, "vcodec": vcodec, "acodec": acodec}


def test_build_qualities_offers_tiers_up_to_tallest_with_sizes():
    formats = [
        _fmt(360, 50), _fmt(720, 150), _fmt(1080, 300),
        {"vcodec": "none", "acodec": "opus", "filesize": 10},
    ]
    options, audio = build_qualities(formats)
    assert audio == 10
    assert [o.height for o in options] == [1080, 720, 480, 360]
    by_height = {o.height: o for o in options}
    assert by_height[1080].size_bytes == 310
    assert by_height[480].size_bytes == 60  # 360p stream (50) + audio (10)
    assert by_height[1080].tier == "Full HD"


def test_build_qualities_without_video_formats_is_empty():
    assert build_qualities([{"vcodec": "none", "acodec": "opus"}])[0] == []


def test_video_options_roundtrip_and_bad_json():
    opts = VideoOptions(format="mp3", height=720, subtitles=True)
    assert VideoOptions.from_json(opts.to_json()) == opts
    assert VideoOptions.from_json("{broken") == VideoOptions()
    assert VideoOptions.from_json(None) == VideoOptions()


def test_ydl_options_for_video_and_audio(tmp_path):
    video = build_ydl_options(VideoOptions(height=720, subtitles=True), str(tmp_path), connections=4)
    assert "height<=720" in video["format"]
    assert video["noplaylist"] is True
    assert video["writesubtitles"] is True
    assert video["concurrent_fragment_downloads"] == 4
    audio = build_ydl_options(VideoOptions(format="mp3", playlist=True), str(tmp_path))
    assert audio["postprocessors"][0]["preferredcodec"] == "mp3"
    assert audio["noplaylist"] is False
    assert "%(playlist_index)" in audio["outtmpl"]


def test_display_name_strips_illegal_characters():
    assert display_name('A: B/C?', VideoOptions()) == "A_ B_C_.mp4"
    assert display_name("", VideoOptions(format="mp3")) == "video.mp3"


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: emits progress, then returns info like a real run."""

    def __init__(self, params, steps=None, fail=None):
        self.params = params
        self.steps = steps
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if self.fail:
            raise RuntimeError("ERROR: Video unavailable")
        for hook in self.params["progress_hooks"]:
            hook({"status": "downloading", "filename": "a.f137.mp4", "downloaded_bytes": 50,
                  "total_bytes": 100, "speed": 10.0, "eta": 5})
            hook({"status": "finished", "filename": "a.f137.mp4", "downloaded_bytes": 100, "total_bytes": 100})
        out = os.path.join(os.path.dirname(self.params["outtmpl"]), "Clip.mp4")
        return {"requested_downloads": [{"filepath": out}]}


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    yield DownloadRepository(db)
    db.close()


def _make_record(repo, tmp_path):
    rec = DownloadRecord(
        id=None, url="https://youtu.be/x", filename="Clip.mp4",
        destination_path=str(tmp_path / "Video" / "Clip.mp4"), category="Video",
        total_size=-1, status=DownloadStatus.QUEUED, kind="video", source="YouTube",
        options=VideoOptions().to_json(),
    )
    rec.id = repo.create_download(rec)
    return rec


def test_video_task_completes_and_records_real_filename(repo, tmp_path):
    rec = _make_record(repo, tmp_path)
    events: list[DownloadEvent] = []
    task = VideoTask(rec, repo, events.append, ydl_factory=FakeYDL)
    task.start()
    assert events[-1].status == DownloadStatus.COMPLETED
    stored = repo.get_download(rec.id)
    assert stored.status == DownloadStatus.COMPLETED
    assert stored.filename == "Clip.mp4"
    assert stored.kind == "video" and stored.source == "YouTube"
    assert stored.total_size == 100 and stored.downloaded_bytes == 100
    assert any(e.status == DownloadStatus.DOWNLOADING and e.downloaded_bytes == 50 for e in events)


def test_video_task_failure_is_reported_without_ansi_or_prefix(repo, tmp_path):
    rec = _make_record(repo, tmp_path)
    events: list[DownloadEvent] = []
    task = VideoTask(rec, repo, events.append, ydl_factory=lambda p: FakeYDL(p, fail=True))
    task.start()
    assert events[-1].status == DownloadStatus.FAILED
    assert events[-1].error_message == "Video unavailable"


def test_video_task_pause_interrupts_and_reports_paused(repo, tmp_path):
    rec = _make_record(repo, tmp_path)
    events: list[DownloadEvent] = []
    task = VideoTask(rec, repo, events.append, ydl_factory=FakeYDL)
    task.pause()
    # start() clears the flags, so simulate a pause arriving mid-download via the first progress hook
    orig = task._on_progress

    def pausing_hook(d):
        task._pause.set()
        orig(d)

    class PausingYDL(FakeYDL):
        def __init__(self, params):
            params = dict(params, progress_hooks=[pausing_hook])
            super().__init__(params)

    task._ydl_factory = PausingYDL
    task.start()
    assert events[-1].status == DownloadStatus.PAUSED
    assert repo.get_download(rec.id).status == DownloadStatus.PAUSED


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, filename TEXT NOT NULL,"
                 " destination_path TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Other', total_size INTEGER NOT NULL DEFAULT -1,"
                 " status TEXT NOT NULL DEFAULT 'queued', downloaded_bytes INTEGER NOT NULL DEFAULT 0, connections INTEGER NOT NULL DEFAULT 8,"
                 " priority INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, completed_at TEXT, scheduled_at TEXT, error_message TEXT,"
                 " retry_count INTEGER NOT NULL DEFAULT 0, supports_ranges INTEGER NOT NULL DEFAULT 1, speed_limit_bytes INTEGER)")
    conn.execute("INSERT INTO downloads (url, filename, destination_path, created_at) VALUES ('u','f','p','2020')")
    conn.commit()
    conn.close()
    db = Database(path)
    repo = DownloadRepository(db)
    (rec,) = repo.list_downloads()
    assert rec.kind == "file" and rec.source == "Direct link" and rec.options is None
    db.close()
