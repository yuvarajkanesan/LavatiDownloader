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
    backend = load_backend()
    assert isinstance(backend, NullBackend) and not backend.available and backend.snapshot() == []


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
