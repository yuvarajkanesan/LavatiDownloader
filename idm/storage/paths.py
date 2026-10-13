"""OS-appropriate user data/config/download directory resolution."""

from __future__ import annotations

import re
from pathlib import Path

import platformdirs

APP_NAME = "IDM Downloader"
APP_AUTHOR = "idm-downloader"

CATEGORY_SUBFOLDERS = {
    "Documents": "Documents",
    "Video": "Video",
    "Music": "Music",
    "Compressed": "Compressed",
    "Programs": "Programs",
    "Other": "Other",
}

EXTENSION_CATEGORY_MAP: dict[str, str] = {
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents",
    ".txt": "Documents", ".xls": "Documents", ".xlsx": "Documents",
    ".ppt": "Documents", ".pptx": "Documents",
    ".mp4": "Video", ".mkv": "Video", ".avi": "Video", ".mov": "Video",
    ".webm": "Video", ".flv": "Video",
    ".mp3": "Music", ".wav": "Music", ".flac": "Music", ".aac": "Music",
    ".ogg": "Music", ".m4a": "Music",
    ".zip": "Compressed", ".rar": "Compressed", ".7z": "Compressed",
    ".tar": "Compressed", ".gz": "Compressed",
    ".exe": "Programs", ".msi": "Programs", ".dmg": "Programs",
    ".pkg": "Programs", ".deb": "Programs", ".rpm": "Programs",
    ".appimage": "Programs",
}

_WINDOWS_RESERVED_STEMS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_UNSAFE_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_FILENAME_LENGTH = 255


def sanitize_filename(name: str | None, fallback: str = "download") -> str:
    """Reduce an untrusted filename (from a Content-Disposition header, a
    URL, or a user-editable field) to a bare, safe basename.

    This is a security boundary, not cosmetic cleanup: a server we're
    downloading from controls the Content-Disposition header, and that
    value flows straight into os.path.join(dest_dir, filename) to build the
    write path. Without this, a malicious/compromised/MITM'd server could
    send `filename="../../../Startup/evil.exe"` (path traversal out of the
    download folder) or an absolute path like `C:\\Windows\\System32\\x.dll`
    or `/etc/passwd` -- os.path.join silently DISCARDS its first argument
    when the second is absolute, so an absolute "filename" would ignore
    dest_dir entirely and let the server pick the write location outright.
    """
    if not name:
        return fallback

    # Keep only the final path segment, whichever separator style was used
    # -- this alone defeats both "../../x" (the ".." segments are simply
    # discarded) and a leading drive letter/UNC prefix on "C:\x\y" (only
    # "y" survives), without needing to special-case either.
    candidate = name.replace("\\", "/").rsplit("/", 1)[-1]

    candidate = _UNSAFE_FILENAME_CHARS_RE.sub("_", candidate).strip(" .")
    if candidate in ("", ".", ".."):
        return fallback

    stem, dot, ext = candidate.rpartition(".")
    name_to_check = stem if dot else candidate
    if name_to_check.upper() in _WINDOWS_RESERVED_STEMS:
        candidate = f"_{candidate}"

    if len(candidate) > _MAX_FILENAME_LENGTH:
        if dot and len(ext) < _MAX_FILENAME_LENGTH - 1:
            candidate = f"{stem[:_MAX_FILENAME_LENGTH - len(ext) - 1]}.{ext}"
        else:
            candidate = candidate[:_MAX_FILENAME_LENGTH]

    return candidate or fallback


def category_for_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return EXTENSION_CATEGORY_MAP.get(ext, "Other")


def user_data_dir() -> Path:
    path = Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_config_dir() -> Path:
    path = Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_database_path() -> Path:
    return user_data_dir() / "idm.sqlite3"


def default_downloads_root() -> Path:
    path = Path(platformdirs.user_downloads_dir()) / "Lavati Downloader"
    path.mkdir(parents=True, exist_ok=True)
    return path


def category_folder(root: Path | str, category: str) -> Path:
    # Callers pass either a Path (default_downloads_root()) or a plain str
    # (a user-configured folder loaded back out of settings) -- coerce here
    # once rather than trusting every call site to do it.
    sub = CATEGORY_SUBFOLDERS.get(category, "Other")
    path = Path(root) / sub
    path.mkdir(parents=True, exist_ok=True)
    return path
