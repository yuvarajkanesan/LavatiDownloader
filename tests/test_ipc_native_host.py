import io
import json
import struct
import threading
import uuid

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

import idm.ipc as ipc
from idm import native_host
from idm.gui.ipc_server import IpcServer


def test_native_message_framing_roundtrip():
    buf = io.BytesIO()
    native_host.write_message(buf, {"type": "add", "url": "https://x/ü"})
    buf.seek(0)
    assert native_host.read_message(buf) == {"type": "add", "url": "https://x/ü"}
    assert native_host.read_message(buf) is None  # clean EOF


def test_native_message_rejects_oversized_length():
    stream = io.BytesIO(struct.pack("<I", native_host.MAX_MESSAGE + 1))
    with pytest.raises(ValueError):
        native_host.read_message(stream)


def test_send_request_without_server_raises_not_running(monkeypatch):
    monkeypatch.setattr(ipc, "pipe_name", lambda: "LavatiDownloader-test-" + uuid.uuid4().hex)
    with pytest.raises(ipc.NotRunning):
        ipc.send_request({"type": "config"}, timeout=0.2)


def test_ipc_roundtrip_through_real_pipe(qapp, monkeypatch):
    name = "LavatiDownloader-test-" + uuid.uuid4().hex
    monkeypatch.setattr(ipc, "pipe_name", lambda: name)
    seen = []

    def handler(message):
        seen.append(message)
        if message.get("type") == "boom":
            raise RuntimeError("bad")
        return {"echo": message.get("url")}

    server = IpcServer(handler, name=name)
    assert server.start()
    results = {}

    def client():
        results["good"] = ipc.send_request({"type": "add", "url": "https://a/b"}, timeout=5)
        results["bad"] = ipc.send_request({"type": "boom"}, timeout=5)

    thread = threading.Thread(target=client)
    thread.start()
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if not thread.is_alive() else None)
    poll.start(20)
    QTimer.singleShot(8000, loop.quit)
    loop.exec()
    thread.join(1)
    server.stop()
    assert results["good"] == {"echo": "https://a/b", "ok": True}
    assert results["bad"]["ok"] is False and "bad" in results["bad"]["error"]
    assert seen[0]["type"] == "add"


def test_relay_reports_clearly_when_app_is_not_running(monkeypatch):
    monkeypatch.setattr(ipc, "pipe_name", lambda: "LavatiDownloader-test-" + uuid.uuid4().hex)
    reply = native_host.relay({"type": "config"}, launch=False)
    assert reply["ok"] is False
