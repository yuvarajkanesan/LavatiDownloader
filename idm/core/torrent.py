"""Torrent data model and the engine seam.

The Torrents screens render `TorrentRecord`s handed over by a `TorrentBackend`. The real engine is libtorrent
(`torrent_engine.LibtorrentBackend`); where libtorrent is not installed `load_backend()` returns a `NullBackend`
that says so and the screens stay empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TorrentState(str, Enum):
    METADATA = "metadata"  # a magnet link still looking for its file list
    DOWNLOADING = "downloading"
    SEEDING = "seeding"
    PAUSED = "paused"
    CHECKING = "checking"
    ERROR = "error"


# file priorities as libtorrent numbers them: 0 = skip, 4 = normal, 7 = high
PRIORITY_SKIP, PRIORITY_NORMAL, PRIORITY_HIGH = 0, 4, 7


@dataclass
class TorrentFile:
    path: str
    size: int
    progress: float = 0.0  # 0..1
    index: int = 0
    priority: int = PRIORITY_NORMAL


@dataclass
class TorrentPeer:
    address: str
    client: str = ""
    progress: float = 0.0
    down_speed: int = 0
    up_speed: int = 0


@dataclass
class TorrentTracker:
    url: str
    status: str = ""
    seeds: int = 0
    peers: int = 0


@dataclass
class TorrentRecord:
    id: str  # info-hash
    name: str
    total_size: int
    downloaded: int = 0
    uploaded: int = 0
    state: TorrentState = TorrentState.PAUSED
    down_speed: int = 0  # bytes/s
    up_speed: int = 0
    seeds: int = 0
    peers: int = 0
    eta_seconds: float | None = None
    save_path: str = ""
    pieces: list[bool] = field(default_factory=list)  # True = piece present, for the pieces grid
    files: list[TorrentFile] = field(default_factory=list)
    peer_list: list[TorrentPeer] = field(default_factory=list)
    trackers: list[TorrentTracker] = field(default_factory=list)

    @property
    def progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return min(1.0, self.downloaded / self.total_size)

    @property
    def ratio(self) -> float:
        return self.uploaded / self.downloaded if self.downloaded > 0 else 0.0


@dataclass
class TorrentPreview:
    """What the Add torrent sheet shows before anything is downloaded."""

    id: str
    ready: bool = False  # False while a magnet link is still fetching its file list
    name: str = ""
    total_size: int = 0
    files: list[TorrentFile] = field(default_factory=list)
    error: str = ""


class TorrentBackend:
    """What the UI needs from a torrent engine. All methods may be called from the GUI thread and must not block."""

    available = False
    unavailable_reason = ""

    def snapshot(self) -> list[TorrentRecord]:
        """Every torrent, cheap fields only (no piece map or file/peer/tracker lists)."""
        return []

    def detail(self, torrent_id: str) -> TorrentRecord | None:
        """One torrent with its piece map, files, peers and trackers filled in."""
        return None

    def preview_magnet(self, magnet: str, save_dir: str) -> str:
        raise NotImplementedError

    def preview_file(self, path: str, save_dir: str) -> str:
        raise NotImplementedError

    def preview(self, preview_id: str) -> TorrentPreview | None:
        raise NotImplementedError

    def commit_preview(self, preview_id: str, selected: list[int], sequential: bool, save_dir: str) -> None:
        raise NotImplementedError

    def cancel_preview(self, preview_id: str) -> None:
        raise NotImplementedError

    def set_file_priority(self, torrent_id: str, file_index: int, priority: int) -> None:
        raise NotImplementedError

    def pause(self, torrent_id: str) -> None:
        raise NotImplementedError

    def resume(self, torrent_id: str) -> None:
        raise NotImplementedError

    def remove(self, torrent_id: str, delete_files: bool = False) -> None:
        raise NotImplementedError

    def shutdown(self) -> None:
        """Save state and stop. Called once when the app quits."""


class NullBackend(TorrentBackend):
    available = False
    unavailable_reason = (
        "Torrent downloading isn't included in this build yet. The Torrents screen is ready, "
        "but no BitTorrent engine is installed."
    )


def is_magnet(text: str) -> bool:
    return text.strip().lower().startswith("magnet:?")


def load_backend(state_dir=None) -> TorrentBackend:
    """libtorrent when it is installed (and starts), else a NullBackend that explains why not."""
    try:
        import libtorrent  # noqa: F401
    except ImportError:
        return NullBackend()
    try:
        from idm.core.torrent_engine import LibtorrentBackend
        return LibtorrentBackend(state_dir)
    except Exception as exc:  # noqa: BLE001 - never let the engine stop the app from starting
        backend = NullBackend()
        backend.unavailable_reason = f"The torrent engine could not start: {exc}"
        return backend
