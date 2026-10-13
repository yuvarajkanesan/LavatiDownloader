from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

import requests

from idm.storage.paths import sanitize_filename

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; LavatiDownloader/0.1; +https://example.invalid)"
)
DEFAULT_TIMEOUT = 15  # seconds, for probing only

_FILENAME_STAR_RE = re.compile(r"filename\*=(?:UTF-8'')?([^;]+)", re.IGNORECASE)
_FILENAME_RE = re.compile(r'filename="?([^";]+)"?', re.IGNORECASE)


@dataclass(slots=True)
class ProbeResult:
    filename: str
    total_size: int  # -1 if unknown
    supports_ranges: bool
    content_type: str | None


def _filename_from_content_disposition(header: str) -> str | None:
    star_match = _FILENAME_STAR_RE.search(header)
    if star_match:
        return unquote(star_match.group(1).strip())
    match = _FILENAME_RE.search(header)
    if match:
        return unquote(match.group(1).strip())
    return None


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = PurePosixPath(unquote(path)).name
    return name or "download"


def filename_for(url: str, content_disposition: str | None) -> str:
    if content_disposition:
        name = _filename_from_content_disposition(content_disposition)
        if name:
            return sanitize_filename(name)
    return sanitize_filename(_filename_from_url(url))


def probe_url(
    url: str,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> ProbeResult:
    """Determine filename, size, and Range support without downloading the body."""
    sess = session or requests.Session()
    headers = {"User-Agent": DEFAULT_USER_AGENT}

    resp = sess.head(url, headers=headers, allow_redirects=True, timeout=timeout)
    if resp.status_code >= 400 or "Content-Length" not in resp.headers:
        # Some servers reject/misreport HEAD; fall back to a ranged GET of 1 byte.
        range_headers = {**headers, "Range": "bytes=0-0"}
        resp = sess.get(
            url, headers=range_headers, allow_redirects=True,
            timeout=timeout, stream=True,
        )
        resp.close()

    resp.raise_for_status()

    accept_ranges = resp.headers.get("Accept-Ranges", "").lower()
    supports_ranges = accept_ranges == "bytes" or resp.status_code == 206

    total_size = -1
    if resp.status_code == 206 and "Content-Range" in resp.headers:
        total_size = int(resp.headers["Content-Range"].rsplit("/", 1)[-1])
    elif "Content-Length" in resp.headers:
        total_size = int(resp.headers["Content-Length"])

    filename = filename_for(str(resp.url), resp.headers.get("Content-Disposition"))

    return ProbeResult(
        filename=filename,
        total_size=total_size,
        supports_ranges=supports_ranges,
        content_type=resp.headers.get("Content-Type"),
    )
