from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from idm import browser_integration
from idm.gui import theme
from idm.gui.icons import make_app_icon
from idm.gui.main_window import MainWindow
from idm.ipc import NotRunning, send_request
from idm.storage.db import Database
from idm.storage.paths import default_database_path
from idm.storage.repository import DownloadRepository


def _load_fonts() -> None:
    folder = Path(__file__).resolve().parent / "gui" / "fonts"
    for font in folder.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))


def _already_running() -> bool:
    """A second launch just brings the running window forward."""
    try:
        return bool(send_request({"type": "show"}, timeout=1.5).get("ok"))
    except NotRunning:
        return False


def main() -> int:
    background = "--background" in sys.argv  # started by the browser: stay in the tray until needed
    if _already_running():
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("Lavati Downloader")
    app.setOrganizationName("idm-downloader")
    app.setWindowIcon(make_app_icon())
    _load_fonts()
    # Applied at the QApplication level (not per-window) so every dialog --
    # each its own top-level widget -- picks up the same look automatically.
    app.setStyleSheet(theme.stylesheet())
    # We hide (not close) the main window to keep the app alive in the tray;
    # without this, Qt would quit the moment the window is hidden/closed.
    app.setQuitOnLastWindowClosed(False)

    db_path = default_database_path()
    db = Database(db_path)
    repo = DownloadRepository(db)
    try:
        browser_integration.register(db_path.parent)
    except OSError:
        pass  # browser integration is optional; the app works without it

    window = MainWindow(repo)
    if not background:
        window.show()

    exit_code = app.exec()
    db.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
