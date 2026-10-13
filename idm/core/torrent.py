"""Torrent data model and the engine seam.

The Torrents screens render `TorrentRecord`s handed over by a `TorrentBackend`. No BitTorrent engine ships in
this build: libtorrent has no release for Python 3.14 yet, so `load_backend()` returns a `NullBackend` that says
so. A real backend (libtorrent) implements the same interface and the screens work unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TorrentState(str, Enum):
    DOWNLOADING = "downloading"
    SEEDING = "seeding"
    PAUSED = "paused"
    CHECKING = "checking"
    ERROR = "error"


@dataclass
class TorrentFile:
    path: str
    size: int
    progress: float = 0.0  # 0..1


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


class TorrentBackend:
    """What the UI needs from a torrent engine. All methods may be called from the GUI thread and must not block."""

    available = False
    unavailable_reason = ""

    def snapshot(self) -> list[TorrentRecord]:
        return []

    def add_magnet(self, magnet: str, save_dir: str) -> None:
        raise NotImplementedError

    def add_file(self, path: str, save_dir: str) -> None:
        raise NotImplementedError

    def pause(self, torrent_id: str) -> None:
        raise NotImplementedError

    def resume(self, torrent_id: str) -> None:
        raise NotImplementedError

    def remove(self, torrent_id: str) -> None:
        raise NotImplementedError


class NullBackend(TorrentBackend):
    available = False
    unavailable_reason = (
        "Torrent downloading isn't included in this build yet. The Torrents screen is ready, "
        "but no BitTorrent engine is installed."
    )


def is_magnet(text: str) -> bool:
    return text.strip().lower().startswith("magnet:?")


def load_backend() -> TorrentBackend:
    """The engine to use. Only a NullBackend for now; a libtorrent backend plugs in here."""
    return NullBackend()
