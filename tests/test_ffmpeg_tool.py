import hashlib
import lzma
import threading

import pytest
import responses

from idm.core import ffmpeg_tool
from idm.core.video import VideoOptions, needs_ffmpeg

URL = "https://example.test/ffmpeg.exe.xz"
EXE = b"MZ-fake-ffmpeg" * 1000
PACKED = lzma.compress(EXE)
SHA = hashlib.sha256(PACKED).hexdigest()


def test_needs_ffmpeg():
    assert needs_ffmpeg(VideoOptions(format="mp3"))
    assert needs_ffmpeg(VideoOptions(format="mp4", join_streams=True))
    assert not needs_ffmpeg(VideoOptions(format="mp4", join_streams=False))


@responses.activate
def test_download_verifies_unpacks_and_reports_progress(tmp_path):
    responses.add(responses.GET, URL, body=PACKED, headers={"Content-Length": str(len(PACKED))})
    seen = []
    path = ffmpeg_tool.download_ffmpeg(progress=lambda d, t: seen.append((d, t)), url=URL, sha256=SHA, dest_dir=tmp_path)
    assert path.read_bytes() == EXE
    assert seen[-1] == (len(PACKED), len(PACKED))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ffmpeg.exe"]  # no temp files left


@responses.activate
def test_wrong_checksum_is_rejected_and_nothing_is_installed(tmp_path):
    responses.add(responses.GET, URL, body=PACKED)
    with pytest.raises(ffmpeg_tool.FfmpegDownloadError, match="checksum"):
        ffmpeg_tool.download_ffmpeg(url=URL, sha256="0" * 64, dest_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@responses.activate
def test_network_failure_is_reported(tmp_path):
    responses.add(responses.GET, URL, status=404)
    with pytest.raises(ffmpeg_tool.FfmpegDownloadError, match="could not download"):
        ffmpeg_tool.download_ffmpeg(url=URL, sha256=SHA, dest_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@responses.activate
def test_cancel_stops_the_download(tmp_path):
    responses.add(responses.GET, URL, body=PACKED)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ffmpeg_tool.FfmpegDownloadError, match="cancelled"):
        ffmpeg_tool.download_ffmpeg(url=URL, sha256=SHA, dest_dir=tmp_path, cancel=cancel)
    assert list(tmp_path.iterdir()) == []


def test_env_override_wins(tmp_path, monkeypatch):
    fake = tmp_path / "ff.exe"
    fake.write_bytes(b"x")
    monkeypatch.setenv("IDM_FFMPEG", str(fake))
    assert ffmpeg_tool.ffmpeg_path() == str(fake)
