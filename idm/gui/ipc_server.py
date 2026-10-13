"""App side of idm.ipc: accepts requests from the browser host / a second launch and hands them to the main window."""

from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from idm.ipc import pipe_name

MAX_REQUEST_BYTES = 1 << 20


class IpcServer(QObject):
    """`handler(message: dict) -> dict` runs on the GUI thread for every request."""

    def __init__(self, handler: Callable[[dict], dict], parent=None, name: str | None = None):
        super().__init__(parent)
        self._handler = handler
        self._name = name or pipe_name()
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)

    def start(self) -> bool:
        if self._server.isListening():
            return True
        QLocalServer.removeServer(self._name)  # stale socket file after a crash (no-op for pipes)
        return self._server.listen(self._name)

    def stop(self) -> None:
        self._server.close()

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            buffer = bytearray()

            def on_ready(sock=socket, buf=buffer):
                buf.extend(bytes(sock.readAll()))
                if b"\n" in buf or len(buf) > MAX_REQUEST_BYTES:
                    self._reply(sock, bytes(buf))

            socket.readyRead.connect(on_ready)
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                on_ready()

    def _reply(self, socket: QLocalSocket, raw: bytes) -> None:
        try:
            request = json.loads(raw.split(b"\n", 1)[0])
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            response = self._handler(request) or {}
            response.setdefault("ok", True)
        except Exception as exc:  # noqa: BLE001 - never let a bad request crash the app
            response = {"ok": False, "error": str(exc)}
        socket.readyRead.disconnect()
        socket.write(json.dumps(response).encode() + b"\n")
        socket.flush()
        socket.disconnectFromServer()
