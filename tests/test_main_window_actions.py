"""Regression tests for the main window's entry points, driven through real Qt dispatch.

History: QAction.triggered / QPushButton.clicked pass a bool (checked state) positionally to the connected
slot. An "Add" button once fed that bool into `_open_add_dialog(initial_url: str)` and QLineEdit(bool) raised,
so the dialog never opened. Calling the method directly (as other tests do) never passes that bool; only a real
`click()` does, which is what these tests use.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from idm.gui.main_window import MainWindow
from idm.storage.db import Database
from idm.storage.repository import DownloadRepository


def _make_window(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    window = MainWindow(DownloadRepository(db))
    window._manager.stop_queue()  # these tests only care about the UI
    window._queue_schedule.stop()
    window._ipc.stop()
    window.show()
    return db, window


def _click_and_close_dialog(window, widget) -> bool:
    outcome = {"opened": False, "url": None}

    def close_modal_dialog_if_present():
        dialog = QApplication.activeModalWidget()
        if dialog is not None:
            outcome["opened"] = True
            outcome["url"] = dialog._url_edit.text()
            dialog.reject()

    QTimer.singleShot(300, close_modal_dialog_if_present)
    widget.click()  # blocks until the timer above closes the modal dialog
    return outcome


def test_add_button_opens_dialog_via_real_qt_click(qapp, tmp_path):
    db, window = _make_window(tmp_path)
    outcome = _click_and_close_dialog(window, window._add_button)
    assert outcome["opened"] is True
    db.close()


def test_link_bar_text_prefills_the_dialog_and_clears(qapp, tmp_path):
    db, window = _make_window(tmp_path)
    window._link_edit.setText("https://example.com/file.zip")
    outcome = _click_and_close_dialog(window, window._add_button)
    assert outcome["url"] == "https://example.com/file.zip"
    assert window._link_edit.text() == ""
    db.close()


def test_sidebar_filters_and_counts(qapp, tmp_path):
    from idm.storage.models import DownloadRecord, DownloadStatus
    db = Database(tmp_path / "t.sqlite3")
    repo = DownloadRepository(db)
    for name, status, category in (("a.mp4", DownloadStatus.COMPLETED, "Video"),
                                   ("b.zip", DownloadStatus.PAUSED, "Compressed"),
                                   ("c.mp3", DownloadStatus.COMPLETED, "Music")):
        repo.create_download(DownloadRecord(id=None, url=f"https://x/{name}", filename=name,
                                            destination_path=f"/tmp/{name}", category=category,
                                            total_size=10, status=status))
    window = MainWindow(repo)
    window._manager.stop_queue()
    window._queue_schedule.stop()
    window._ipc.stop()
    counts = [b._count.text() for b in window._nav_buttons]
    assert counts[:4] == ["3", "0", "1", "2"]  # all, active, queued and paused, completed
    window._nav_buttons[3].click()  # Completed
    assert window._proxy.rowCount() == 2
    assert window._title.text() == "Completed"
    window._nav_buttons[5].click()  # Documents
    assert window._proxy.rowCount() == 0
    db.close()


def test_settings_page_roundtrip_applies_to_the_manager(qapp, tmp_path):
    db, window = _make_window(tmp_path)
    window._open_settings()
    page = window._settings_page
    page._concurrent.setCurrentIndex(page._concurrent.findData("5"))
    assert window._repo.get_setting("max_concurrent_downloads") == "5"
    assert window._manager._max_concurrent == 5
    page._limit_check.setChecked(True)
    page._limit_spin.setValue(500)
    assert window._repo.get_setting("global_speed_limit_kbps") == "500"
    page._sched_on.setChecked(True)
    assert window._repo.get_setting("schedule_enabled") == "1"
    db.close()


def test_ipc_handler_config_and_add(qapp, tmp_path):
    db, window = _make_window(tmp_path)
    assert window._handle_ipc({"type": "config"}) == {"videoButton": True, "captureDownloads": True}
    assert window._handle_ipc({"type": "add", "url": "javascript:alert(1)"})["ok"] is False
    assert window._handle_ipc({"type": "nope"})["ok"] is False
    db.close()


def test_torrents_mode_switches_pages_and_explains_missing_engine(qapp, tmp_path):
    db, window = _make_window(tmp_path)
    window._mode_tabs._buttons["torrents"].click()
    assert window._mode == "torrents"
    assert window._pages.currentWidget() is window._torrents_page
    assert window._link_edit.placeholderText() == "Paste a magnet link"
    assert window._torrents_page.empty.isVisibleTo(window._torrents_page)
    assert "isn't included" in window._torrents_page.empty.text()
    window._torrents_nav.click()  # the sidebar entry also lands on the Torrents screen
    assert window._mode == "torrents"
    window._mode_tabs._buttons["downloads"].click()
    assert window._pages.currentWidget() is not window._torrents_page
    db.close()
