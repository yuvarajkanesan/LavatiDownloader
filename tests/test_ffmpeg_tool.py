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


import io
import zipfile

FB_ZIP_URL = "https://mirror.test/ffmpeg.zip"
FB_SHA_URL = "https://mirror.test/ffmpeg.zip.sha256"


def _zip_bytes(member="ffmpeg-7.1-essentials_build/bin/ffmpeg.exe"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, EXE)
        z.writestr("ffmpeg-7.1-essentials_build/bin/ffplay.exe", b"other")
    return buf.getvalue()


@responses.activate
def test_fallback_extracts_ffmpeg_from_the_public_zip(tmp_path):
    data = _zip_bytes()
    responses.add(responses.GET, FB_SHA_URL, body=hashlib.sha256(data).hexdigest() + " *ffmpeg.zip\n")
    responses.add(responses.GET, FB_ZIP_URL, body=data)
    path = ffmpeg_tool.download_ffmpeg_fallback(zip_url=FB_ZIP_URL, sha_url=FB_SHA_URL, dest_dir=tmp_path)
    assert path.read_bytes() == EXE
    assert [p.name for p in tmp_path.iterdir()] == ["ffmpeg.exe"]


@responses.activate
def test_fallback_rejects_a_bad_checksum(tmp_path):
    responses.add(responses.GET, FB_SHA_URL, body="0" * 64)
    responses.add(responses.GET, FB_ZIP_URL, body=_zip_bytes())
    with pytest.raises(ffmpeg_tool.FfmpegDownloadError, match="checksum"):
        ffmpeg_tool.download_ffmpeg_fallback(zip_url=FB_ZIP_URL, sha_url=FB_SHA_URL, dest_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@responses.activate
def test_any_falls_back_when_the_release_is_missing(tmp_path, monkeypatch):
    data = _zip_bytes()
    responses.add(responses.GET, ffmpeg_tool.FFMPEG_URL, status=404)
    responses.add(responses.GET, ffmpeg_tool.FALLBACK_SHA_URL, body=hashlib.sha256(data).hexdigest())
    responses.add(responses.GET, ffmpeg_tool.FALLBACK_ZIP_URL, body=data)
    path = ffmpeg_tool.download_ffmpeg_any(dest_dir=tmp_path)
    assert path.read_bytes() == EXE


@responses.activate
def test_any_reports_both_failures(tmp_path):
    responses.add(responses.GET, ffmpeg_tool.FFMPEG_URL, status=404)
    responses.add(responses.GET, ffmpeg_tool.FALLBACK_SHA_URL, status=500)
    with pytest.raises(ffmpeg_tool.FfmpegDownloadError, match="backup source failed"):
        ffmpeg_tool.download_ffmpeg_any(dest_dir=tmp_path)
