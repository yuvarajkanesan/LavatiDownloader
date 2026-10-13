from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from idm.core.clipboard_detect import extract_first_url, looks_like_download_url
from idm.core.video import detect_site

POLL_INTERVAL_MS = 1000


class ClipboardMonitor(QObject):
    """Polls the system clipboard on the GUI thread (QClipboard is not
    thread-safe / must be used from the main thread) and signals when new
    text looks like a downloadable file link."""

    download_url_detected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_seen: str | None = None
        self.detect_video_links = True
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._check_clipboard)

    def start(self) -> None:
        self._last_seen = self._current_text()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _current_text(self) -> str:
        clipboard = QApplication.clipboard()
        return clipboard.text() if clipboard else ""

    def _check_clipboard(self) -> None:
        text = self._current_text()
        if not text or text == self._last_seen:
            return
        self._last_seen = text
        if looks_like_download_url(text):
            self.download_url_detected.emit(text)
        elif self.detect_video_links and detect_site(extract_first_url(text) or ""):
            self.download_url_detected.emit(text)
