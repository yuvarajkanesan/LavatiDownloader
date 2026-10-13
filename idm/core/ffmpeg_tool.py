"""The ffmpeg helper that joins separate video and audio streams and converts audio to MP3.

It is not shipped inside the installer (it is 84 MB). The app downloads it once, on first use, from this project's
GitHub release, checks its SHA-256 and keeps it in the user data folder. ffmpeg runs as a separate program.
Build the asset with tools/make_ffmpeg_asset.py and attach it to the release named in FFMPEG_URL.
"""

from __future__ import annotations

import hashlib
import lzma
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

import requests

from idm.storage.paths import user_data_dir

# the release asset: ffmpeg.exe, xz-compressed (see tools/make_ffmpeg_asset.py)
FFMPEG_URL = "https://github.com/yuvarajkanesan/LavatiDownloader/releases/download/ffmpeg-7.1/ffmpeg-win64.exe.xz"
FFMPEG_XZ_SHA256 = "b59354d99090023ec94e319c538406b00aaf20d64c26a6acc64621b0199bfcf2"  # set by make_ffmpeg_asset.py
FFMPEG_DOWNLOAD_MB = 21  # shown in the prompt

CHUNK = 256 * 1024


class FfmpegDownloadError(Exception):
    pass


def tools_dir() -> Path:
    return user_data_dir() / "tools"


def installed_path() -> Path | None:
    path = tools_dir() / "ffmpeg.exe"
    return path if path.exists() else None


def ffmpeg_path() -> str | None:
    """Where ffmpeg is, or None if it has not been downloaded yet. IDM_FFMPEG overrides (handy for development)."""
    override = os.environ.get("IDM_FFMPEG")
    if override and os.path.exists(override):
        return override
    path = installed_path()
    if path:
        return str(path)
    if not getattr(sys, "frozen", False):  # a source checkout can borrow the dev dependency's copy
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001 - not installed: fall through to "not available"
            return None
    return None


def download_ffmpeg(
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
    url: str = FFMPEG_URL,
    sha256: str = FFMPEG_XZ_SHA256,
    dest_dir: Path | None = None,
    session: requests.Session | None = None,
) -> Path:
    """Download, verify and unpack ffmpeg. `progress(done, total)` is called as bytes arrive. Raises
    FfmpegDownloadError on any failure (network, wrong checksum, cancelled); nothing partial is left behind."""
    dest = Path(dest_dir) if dest_dir else tools_dir()
    dest.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".xz", dir=dest)
    os.close(fd)
    tmp = Path(tmp_name)
    exe_tmp = dest / "ffmpeg.exe.part"
    try:
        digest = hashlib.sha256()
        try:
            response = (session or requests).get(url, stream=True, timeout=30)
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as out:
                for chunk in response.iter_content(CHUNK):
                    if cancel is not None and cancel.is_set():
                        raise FfmpegDownloadError("cancelled")
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        except requests.RequestException as exc:
            raise FfmpegDownloadError(f"could not download the video tool: {exc}") from exc
        if digest.hexdigest() != sha256.lower():
            raise FfmpegDownloadError("the downloaded file does not match the expected checksum")
        try:
            with lzma.open(tmp, "rb") as src, open(exe_tmp, "wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
        except (lzma.LZMAError, OSError) as exc:
            raise FfmpegDownloadError(f"could not unpack the video tool: {exc}") from exc
        final = dest / "ffmpeg.exe"
        os.replace(exe_tmp, final)
        return final
    finally:
        for leftover in (tmp, exe_tmp):
            try:
                leftover.unlink()
            except OSError:
                pass
