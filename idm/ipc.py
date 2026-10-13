"""Local channel between the running app and short-lived helpers (the browser's native-messaging host, a second
launch of the app). One JSON object per line over a per-user named pipe; the app answers with one JSON line.

This module is Qt-free so the native host stays tiny; the server side lives in `idm.gui.ipc_server`.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import time


def pipe_name() -> str:
    user = re.sub(r"[^A-Za-z0-9_.-]", "_", getpass.getuser())
    return f"LavatiDownloader-{user}"


def pipe_path() -> str:
    if sys.platform == "win32":
        return "\\\\.\\pipe\\" + pipe_name()
    return os.path.join("/tmp", pipe_name())  # QLocalServer uses a unix socket here on POSIX


class NotRunning(Exception):
    """The app is not listening."""


def send_request(message: dict, timeout: float = 5.0) -> dict:
    """Send one request to the running app and return its reply. Raises NotRunning when nothing is listening."""
    if sys.platform != "win32":
        import socket
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(timeout)
        try:
            sock.connect(pipe_path())
        except OSError as exc:
            raise NotRunning(str(exc)) from exc
        with sock:
            sock.sendall(json.dumps(message).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf or b"{}")

    deadline = time.monotonic() + timeout
    while True:
        try:
            pipe = open(pipe_path(), "r+b", buffering=0)  # noqa: SIM115 - closed below
            break
        except FileNotFoundError as exc:
            raise NotRunning(str(exc)) from exc
        except OSError as exc:  # ERROR_PIPE_BUSY while the server accepts another client
            if time.monotonic() > deadline:
                raise NotRunning(str(exc)) from exc
            time.sleep(0.05)
    with pipe:
        pipe.write(json.dumps(message).encode() + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = pipe.read(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf or b"{}")
