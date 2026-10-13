from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from idm.gui import theme
from idm.gui.icons import make_app_icon
from idm.gui.material_icons import get_icon


class TrayController:
    def __init__(self, main_window, on_quit=None):
        self._window = main_window
        self.icon = QSystemTrayIcon(make_app_icon(), main_window)
        self.icon.setToolTip("Lavati Downloader")

        menu = QMenu()
        show_action = menu.addAction(get_icon("grid", color=theme.NEUTRAL), "Show")
        show_action.triggered.connect(self._show_window)
        menu.addSeparator()
        quit_action = menu.addAction(get_icon("close", color=theme.NEUTRAL), "Quit")
        quit_action.triggered.connect(on_quit or QApplication.instance().quit)

        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.show()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._show_window()

    def _show_window(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def notify(self, title: str, message: str, is_error: bool = False) -> None:
        icon = QSystemTrayIcon.Critical if is_error else QSystemTrayIcon.Information
        self.icon.showMessage(title, message, icon, 5000)
