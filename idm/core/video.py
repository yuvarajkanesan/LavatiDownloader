"""Video / social links: which site a URL belongs to, what formats it offers, and the yt-dlp options for a choice.

The engine side (`video_task.VideoTask`) and the Add Download dialog both go through here, so the quality list the
user picks from is built from the same data that is later used to download it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

# label shown in the UI -> host suffixes that belong to it
SITES: dict[str, tuple[str, ...]] = {
    "YouTube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "Instagram": ("instagram.com",),
    "Facebook": ("facebook.com", "fb.watch", "fb.com"),
    "TikTok": ("tiktok.com",),
    "X": ("x.com", "twitter.com"),
}

# the tiers offered in the quality grid, best first
QUALITY_TIERS: tuple[tuple[int, str], ...] = (
    (2160, "4K"), (1440, "2K"), (1080, "Full HD"), (720, "HD"), (480, "SD"), (360, "Low"),
)


def detect_site(url: str) -> str | None:
    """'YouTube', 'Instagram', ... when the URL points at a supported video site, else None."""
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return None
    for site, suffixes in SITES.items():
        if any(host == s or host.endswith("." + s) for s in suffixes):
            return site
    return None


@dataclass
class VideoOptions:
    format: str = "mp4"  # "mp4" (video) or "mp3" (audio only)
    height: int = 1080  # tallest video to fetch; ignored for mp3
    subtitles: bool = False
    playlist: bool = False
    name_with_uploader: bool = False
    join_streams: bool = True  # fetch separate best video + audio and merge (needs ffmpeg)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str | None) -> "VideoOptions":
        if not text:
            return cls()
        try:
            data = json.loads(text)
        except ValueError:
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class QualityOption:
    height: int
    tier: str  # "Full HD"
    size_bytes: int | None = None  # video + audio estimate, None when the site does not say

    @property
    def title(self) -> str:
        return f"{self.height}p"


@dataclass
class VideoInfo:
    url: str
    site: str
    title: str
    uploader: str = ""
    thumbnail: str = ""
    is_playlist: bool = False
    playlist_count: int = 0
    qualities: list[QualityOption] = field(default_factory=list)
    audio_size_bytes: int | None = None


def _size(fmt: dict) -> int | None:
    return fmt.get("filesize") or fmt.get("filesize_approx")


def build_qualities(formats: list[dict]) -> tuple[list[QualityOption], int | None]:
    """Reduce yt-dlp's format list to the fixed tiers we offer, with size estimates.

    A tier is offered when the video has at least that height (the lowest tier is always offered).
    """
    videos = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("height")]
    audios = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")]
    audio_sizes = [s for s in map(_size, audios) if s]
    audio_size = max(audio_sizes) if audio_sizes else None
    if not videos:
        return [], audio_size
    tallest = max(f["height"] for f in videos)
    options: list[QualityOption] = []
    for height, tier in QUALITY_TIERS:
        if height > tallest and height != QUALITY_TIERS[-1][0]:
            continue
        # what yt-dlp would pick for "bestvideo[height<=h]": the biggest height not above the tier
        candidates = [f for f in videos if f["height"] <= height]
        if not candidates:
            continue
        best_h = max(f["height"] for f in candidates)
        sizes = [s for s in (_size(f) for f in candidates if f["height"] == best_h) if s]
        video_size = max(sizes) if sizes else None
        total = video_size + (audio_size or 0) if video_size else None
        options.append(QualityOption(height=height, tier=tier, size_bytes=total))
    return options, audio_size


def fetch_video_info(url: str, timeout: int = 20) -> VideoInfo:
    """Ask the site what it has. Blocking; call off the GUI thread. Raises on any failure."""
    import yt_dlp

    site = detect_site(url) or "Video"
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "socket_timeout": timeout, "extract_flat": "in_playlist",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise RuntimeError("no video found at that link")
    entries = [e for e in (info.get("entries") or []) if e]
    is_playlist = info.get("_type") == "playlist"
    if is_playlist and "formats" not in info:
        # a playlist link: describe its first video (formats of the rest are fetched while downloading)
        first_url = entries[0].get("url") or entries[0].get("webpage_url") if entries else None
        if first_url:
            with yt_dlp.YoutubeDL({**opts, "noplaylist": True, "extract_flat": False}) as ydl:
                first = ydl.extract_info(first_url, download=False) or {}
        else:
            first = {}
    else:
        first = info
    qualities, audio_size = build_qualities(first.get("formats") or [])
    return VideoInfo(
        url=url, site=site, title=first.get("title") or info.get("title") or "Video",
        uploader=first.get("uploader") or first.get("channel") or "",
        thumbnail=first.get("thumbnail") or "", is_playlist=is_playlist, playlist_count=len(entries),
        qualities=qualities, audio_size_bytes=audio_size,
    )


def ffmpeg_path() -> str | None:
    """The downloaded ffmpeg (see ffmpeg_tool), or None; yt-dlp then falls back to single-file formats."""
    from idm.core import ffmpeg_tool
    return ffmpeg_tool.ffmpeg_path()


def needs_ffmpeg(options: VideoOptions) -> bool:
    """Joining separate streams and extracting MP3 both need ffmpeg."""
    return options.format == "mp3" or options.join_streams


def build_ydl_options(options: VideoOptions, dest_dir: str, connections: int = 8) -> dict:
    """yt-dlp parameters for the user's choices. Hooks and rate limit are added by the task."""
    name = "%(uploader)s - %(title)s" if options.name_with_uploader else "%(title)s"
    if options.playlist:
        outtmpl = f"{dest_dir}/%(playlist_title)s/%(playlist_index)03d - {name}.%(ext)s"
    else:
        outtmpl = f"{dest_dir}/{name}.%(ext)s"
    ydl: dict = {
        "outtmpl": outtmpl,
        "noplaylist": not options.playlist,
        "quiet": True, "no_warnings": True, "noprogress": True,
        "windowsfilenames": True,
        "continuedl": True,
        "concurrent_fragment_downloads": max(1, min(connections, 16)),
        "retries": 5, "fragment_retries": 5,
    }
    ffmpeg = ffmpeg_path()
    if ffmpeg:
        ydl["ffmpeg_location"] = ffmpeg
    if options.format == "mp3":
        ydl["format"] = "bestaudio/best"
        ydl["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        h = int(options.height)
        if ffmpeg and options.join_streams:
            ydl["format"] = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
            ydl["merge_output_format"] = "mp4"
        else:
            ydl["format"] = f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
    if options.subtitles:
        ydl["writesubtitles"] = True
        ydl["subtitleslangs"] = ["en.*", "en"]
    return ydl


_BAD = re.compile(r'[\\/:*?"<>|]')


def display_name(title: str, options: VideoOptions) -> str:
    """File name shown in the list before the download finishes."""
    ext = "mp3" if options.format == "mp3" else "mp4"
    return f"{_BAD.sub('_', title).strip() or 'video'}.{ext}"
