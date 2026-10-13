from __future__ import annotations

import re
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

DOWNLOADABLE_EXTENSIONS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tar.gz", ".tgz",
    ".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".wav", ".flac", ".aac", ".m4a",
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".iso", ".img",
}


def looks_like_download_url(text: str) -> bool:
    """Heuristic: does this clipboard text contain a URL whose path suggests
    a downloadable file (by extension)? Deliberately conservative -- this
    only decides whether to *prompt* the user, never to auto-download."""
    match = _URL_RE.search(text.strip())
    if not match:
        return False
    url = match.group(0)
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in DOWNLOADABLE_EXTENSIONS)


def extract_first_url(text: str) -> str | None:
    match = _URL_RE.search(text.strip())
    return match.group(0) if match else None
