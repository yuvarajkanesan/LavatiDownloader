"""The libtorrent backend, exercised over loopback with real files: no tracker, DHT or internet involved."""

import os
import time
import warnings

import pytest

lt = pytest.importorskip("libtorrent")

from idm.core.torrent import PRIORITY_SKIP, TorrentState  # noqa: E402
from idm.core.torrent_engine import LibtorrentBackend  # noqa: E402

LOCAL = {"listen_interfaces": "127.0.0.1:0", "enable_dht": False, "enable_lsd": False, "enable_upnp": False,
         "enable_natpmp": False}


def wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def content(tmp_path):
    """A two-file torrent plus the data it describes, laid out for seeding straight away."""
    root = tmp_path / "seed"
    folder = root / "Album"
    folder.mkdir(parents=True)
    (folder / "a.bin").write_bytes(os.urandom(200_000))
    (folder / "b.txt").write_bytes(b"hello torrent " * 20_000)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        storage = lt.file_storage()
        lt.add_files(storage, str(folder))
        torrent = lt.create_torrent(storage, piece_size=16384, flags=lt.create_torrent.v1_only)
        lt.set_piece_hashes(torrent, str(root))
    path = tmp_path / "album.torrent"
    path.write_bytes(lt.bencode(torrent.generate()))
    return {"torrent": path, "root": root, "folder": folder}


def make_backend(tmp_path, name):
    return LibtorrentBackend(tmp_path / name, settings=LOCAL)


def seeded(backend, content):
    tid = backend.preview_file(str(content["torrent"]), str(content["root"]))
    backend.commit_preview(tid, [0, 1], False, str(content["root"]))
    assert wait_for(lambda: any(r.state == TorrentState.SEEDING for r in backend.snapshot()))
    return tid


def test_existing_data_is_verified_and_seeds(tmp_path, content):
    backend = make_backend(tmp_path, "a")
    tid = seeded(backend, content)
    detail = backend.detail(tid)
    assert detail.name == "Album" and detail.total_size == 200_000 + 280_000
    assert detail.progress == 1.0 and all(detail.pieces) and len(detail.pieces) == 30
    assert [f.path.replace("\\", "/") for f in detail.files] == ["Album/a.bin", "Album/b.txt"]
    assert all(f.progress == 1.0 for f in detail.files)
    backend.shutdown()


def test_previewing_the_same_torrent_twice_is_refused(tmp_path, content):
    backend = make_backend(tmp_path, "a")
    seeded(backend, content)
    with pytest.raises(ValueError, match="already"):
        backend.preview_file(str(content["torrent"]), str(content["root"]))
    backend.shutdown()


def test_download_from_a_seeder_and_file_selection(tmp_path, content):
    seeder = make_backend(tmp_path, "seeder")
    seeded(seeder, content)
    leecher = make_backend(tmp_path, "leecher")
    dest = tmp_path / "downloads"
    dest.mkdir()
    tid = leecher.preview_file(str(content["torrent"]), str(dest))
    preview = leecher.preview(tid)
    assert preview.ready and [f.index for f in preview.files] == [0, 1] and preview.total_size == 480_000
    leecher.commit_preview(tid, [0], False, str(dest))  # only a.bin
    handle = leecher._handles[tid]
    handle.connect_peer(("127.0.0.1", seeder._session.listen_port()))
    assert wait_for(lambda: leecher.detail(tid).state == TorrentState.SEEDING, 40)
    assert (dest / "Album" / "a.bin").read_bytes() == (content["folder"] / "a.bin").read_bytes()
    detail = leecher.detail(tid)
    assert detail.files[0].progress == 1.0 and detail.files[1].priority == PRIORITY_SKIP
    assert detail.files[1].progress < 0.1  # b.txt shares one piece with a.bin, nothing more
    assert 200_000 <= detail.total_size < 230_000  # only the wanted file's pieces count
    seeder.shutdown()
    leecher.shutdown()


def test_pause_resume_remove(tmp_path, content):
    backend = make_backend(tmp_path, "a")
    tid = seeded(backend, content)
    backend.pause(tid)
    assert wait_for(lambda: backend.detail(tid).state == TorrentState.PAUSED)
    backend.resume(tid)
    assert wait_for(lambda: backend.detail(tid).state == TorrentState.SEEDING)
    backend.remove(tid)
    assert backend.snapshot() == [] and backend.detail(tid) is None
    assert (content["folder"] / "a.bin").exists()  # files are kept unless asked
    backend.shutdown()


def test_torrents_survive_a_restart(tmp_path, content):
    first = make_backend(tmp_path, "a")
    tid = seeded(first, content)
    first.pause(tid)
    wait_for(lambda: first.detail(tid).state == TorrentState.PAUSED)
    first.shutdown()
    del first
    second = make_backend(tmp_path, "a")
    records = second.snapshot()
    assert [r.id for r in records] == [tid]
    assert records[0].state == TorrentState.PAUSED and records[0].name == "Album"
    second.shutdown()


def test_cancelling_a_preview_adds_nothing(tmp_path, content):
    backend = make_backend(tmp_path, "a")
    tid = backend.preview_file(str(content["torrent"]), str(content["root"]))
    assert backend.snapshot() == []  # a preview is not a torrent in the list yet
    backend.cancel_preview(tid)
    assert backend.preview(tid) is None and backend.snapshot() == []
    backend.shutdown()


def test_magnet_without_peers_stays_pending(tmp_path):
    backend = make_backend(tmp_path, "a")
    magnet = "magnet:?xt=urn:btih:" + "ab" * 20 + "&dn=Nothing"
    tid = backend.preview_magnet(magnet, str(tmp_path))
    preview = backend.preview(tid)
    assert preview is not None and preview.ready is False
    backend.cancel_preview(tid)
    backend.shutdown()
