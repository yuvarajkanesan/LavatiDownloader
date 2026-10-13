from __future__ import annotations

import threading

import requests
from PySide6.QtCore import QObject, Signal

from idm.core.http import ProbeResult, probe_url
from idm.core.video import VideoInfo, fetch_video_info


class ProbeWorker(QObject):
    """Runs probe_url() off the GUI thread so the Add Download dialog
    doesn't freeze while waiting on the server's HEAD response."""

    succeeded = Signal(object)  # ProbeResult
    failed = Signal(str)

    def start(self, url: str) -> None:
        thread = threading.Thread(target=self._run, args=(url,), daemon=True)
        thread.start()

    def _run(self, url: str) -> None:
        try:
            result: ProbeResult = probe_url(url)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the dialog
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class VideoInfoWorker(QObject):
    """Asks yt-dlp what a video link offers (formats, sizes, title) off the GUI thread.

    Every start() gets a ticket; results from an older ticket are dropped so a slow answer for a link the user
    has since replaced never overwrites the current one.
    """

    succeeded = Signal(int, object, object)  # ticket, VideoInfo, thumbnail bytes or None
    failed = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ticket = 0

    def start(self, url: str) -> int:
        self._ticket += 1
        ticket = self._ticket
        threading.Thread(target=self._run, args=(ticket, url), daemon=True).start()
        return ticket

    def _run(self, ticket: int, url: str) -> None:
        try:
            info: VideoInfo = fetch_video_info(url)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(ticket, _short(str(exc)))
            return
        thumb = None
        if info.thumbnail:
            try:
                response = requests.get(info.thumbnail, timeout=8)
                if response.ok:
                    thumb = response.content
            except requests.RequestException:
                pass
        self.succeeded.emit(ticket, info, thumb)


def _short(message: str) -> str:
    import re
    message = re.sub(r"\x1b\[[0-9;]*m", "", message).replace("ERROR: ", "").strip()
    return message.splitlines()[0][:200] if message else "unknown error"
