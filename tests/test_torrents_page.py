from idm.core.torrent import NullBackend, TorrentRecord, TorrentState, is_magnet, load_backend
from idm.gui.torrents_page import PiecesGrid, TorrentsPage

GB = 1 << 30


def _t(name, state, size=1000, done=1000, up=0, seeds=1, peers=2):
    return TorrentRecord(id=name, name=name, total_size=size, downloaded=done, uploaded=up, state=state,
                         seeds=seeds, peers=peers, pieces=[True] * 10)


def test_record_math():
    t = _t("a", TorrentState.SEEDING, size=1000, done=1000, up=220)
    assert t.progress == 1.0
    assert abs(t.ratio - 0.22) < 1e-9
    assert _t("b", TorrentState.PAUSED, size=0, done=0).progress == 0.0
    assert _t("c", TorrentState.PAUSED, done=0).ratio == 0.0


def test_magnet_detection_and_null_backend():
    assert is_magnet("  magnet:?xt=urn:btih:abc")
    assert not is_magnet("https://example.com/a.torrent")
    backend = NullBackend()
    assert not backend.available and backend.snapshot() == [] and backend.detail("x") is None


def test_page_filters_by_group_and_shows_detail(qapp):
    page = TorrentsPage()
    page.resize(1000, 700)
    page.show()
    page.set_records([_t("a", TorrentState.SEEDING, up=100), _t("b", TorrentState.PAUSED, done=300),
                      _t("c", TorrentState.DOWNLOADING, done=500)])
    assert page.proxy.rowCount() == 3
    page.set_group("seeding", "Seeding")
    assert page.proxy.rowCount() == 1 and page.title.text() == "Seeding"
    page.set_group(None, "All torrents")
    page.table.selectRow(1)
    assert page.selected().name == "b"
    assert page.detail_name.text() == "b"
    assert page.tile_downloaded.value.text() == "1000 B" or page.tile_downloaded.value.text().endswith("B")


def test_refresh_keeps_selection_when_torrents_are_unchanged(qapp):
    page = TorrentsPage()
    page.show()
    records = [_t("a", TorrentState.SEEDING), _t("b", TorrentState.PAUSED)]
    page.set_records(records)
    page.table.selectRow(1)
    page.set_records([_t("a", TorrentState.SEEDING, up=5), _t("b", TorrentState.PAUSED, done=500)])
    assert page.selected().name == "b"


def test_pieces_grid_bins_when_pieces_outnumber_cells(qapp):
    grid = PiecesGrid()
    grid.resize(200, grid.height())
    grid.set_pieces([True] * 1000 + [False] * 1000)
    cells = grid.cells()
    assert len(cells) == ((200 + 4) // 20) * 3
    assert cells[0] == 1.0 and cells[-1] == 0.0
    grid.set_pieces([True, False])
    assert grid.cells()[:2] == [1.0, 0.0]


# ---- the Add torrent sheet and the main window against the real engine over loopback ----

import os
import time
import warnings

import pytest

lt = pytest.importorskip("libtorrent")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from idm.core.torrent_engine import LibtorrentBackend  # noqa: E402
from idm.gui.add_torrent_dialog import AddTorrentDialog  # noqa: E402

LOCAL = {"listen_interfaces": "127.0.0.1:0", "enable_dht": False, "enable_lsd": False, "enable_upnp": False,
         "enable_natpmp": False}


@pytest.fixture
def torrent_file(tmp_path):
    folder = tmp_path / "data" / "Pack"
    folder.mkdir(parents=True)
    (folder / "one.bin").write_bytes(os.urandom(100_000))
    (folder / "two.bin").write_bytes(os.urandom(60_000))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        storage = lt.file_storage()
        lt.add_files(storage, str(folder))
        torrent = lt.create_torrent(storage, piece_size=16384, flags=lt.create_torrent.v1_only)
        lt.set_piece_hashes(torrent, str(tmp_path / "data"))
    path = tmp_path / "pack.torrent"
    path.write_bytes(lt.bencode(torrent.generate()))
    return path, tmp_path / "data"


def test_add_sheet_lists_files_updates_total_and_commits(qapp, tmp_path, torrent_file):
    path, data = torrent_file
    backend = LibtorrentBackend(tmp_path / "state", settings=LOCAL)
    pid = backend.preview_file(str(path), str(data))
    dialog = AddTorrentDialog(backend, pid, str(data))
    dialog.show()
    assert dialog._preview.ready and dialog._files.rowCount() == 2
    assert dialog._add.isEnabled() and "160" in dialog._total.text().replace(" ", "") or "156" in dialog._total.text()
    dialog._files.item(1, 0).setCheckState(Qt.Unchecked)  # drop two.bin
    assert dialog._selected() == [0] and dialog._add.text().startswith("Add")
    dialog._set_all(False)
    assert not dialog._add.isEnabled()
    dialog._set_all(True)
    dialog._mode.set_value("order")
    dialog.accept()
    assert [r.name for r in backend.snapshot()] == ["Pack"]
    backend.shutdown()


def test_add_sheet_closed_without_adding_forgets_the_torrent(qapp, tmp_path, torrent_file):
    path, data = torrent_file
    backend = LibtorrentBackend(tmp_path / "state", settings=LOCAL)
    pid = backend.preview_file(str(path), str(data))
    dialog = AddTorrentDialog(backend, pid, str(data))
    dialog.reject()
    assert backend.snapshot() == [] and backend.preview(pid) is None
    backend.shutdown()


def test_files_tab_priority_picker_reports_changes(qapp, tmp_path, torrent_file):
    path, data = torrent_file
    backend = LibtorrentBackend(tmp_path / "state", settings=LOCAL)
    pid = backend.preview_file(str(path), str(data))
    backend.commit_preview(pid, [0, 1], False, str(data))
    page = TorrentsPage()
    page.resize(1000, 800)
    page.show()
    page.detail_provider = backend.detail
    seen = []
    page.file_priority_requested.connect(lambda *a: seen.append(a))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not backend.snapshot():
        time.sleep(0.1)
    page.set_records(backend.snapshot())
    page.table.selectRow(0)
    assert page.files_table.rowCount() == 2
    combo = page.files_table.cellWidget(1, 3)
    combo.setCurrentIndex(0)  # Skip
    assert seen and seen[-1][1:] == (1, 0)
    backend.set_file_priority(*seen[-1])
    deadline = time.monotonic() + 5  # libtorrent applies it on its own thread
    while time.monotonic() < deadline and backend.detail(pid).files[1].priority != 0:
        time.sleep(0.05)
    assert backend.detail(pid).files[1].priority == 0
    backend.shutdown()
