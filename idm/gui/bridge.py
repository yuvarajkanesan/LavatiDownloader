"""The only place engine threads touch anything Qt-related.

DownloadManager calls its listeners from arbitrary background threads.
EngineBridge is a QObject living on the main thread; emitting its signal
from a different thread is automatically delivered as a queued connection
by Qt, which is what makes this safe -- everything downstream of
`event_received` runs on the GUI thread like normal Qt code.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from idm.core.events import DownloadEvent


class EngineBridge(QObject):
    event_received = Signal(object)  # DownloadEvent

    def listener(self, event: DownloadEvent) -> None:
        self.event_received.emit(event)
