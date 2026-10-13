"""Chrome / Edge native-messaging host. The browser extension talks to this process over stdin/stdout (4-byte
little-endian length + JSON); each message is relayed to the running app through idm.ipc. If the app is not
running it is started first. Deliberately Qt-free so the executable stays small.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time

from idm.ipc import NotRunning, send_request

MAX_MESSAGE = 1 << 20  # Chrome caps host-bound messages at 1 MB


def read_message(stream) -> dict | None:
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("<I", header)
    if length > MAX_MESSAGE:
        raise ValueError("message too large")
    return json.loads(stream.read(length))


def write_message(stream, message: dict) -> None:
    data = json.dumps(message).encode("utf-8")
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()


def app_command() -> list[str] | None:
    """How to start the app: the sibling executable when installed, `python -m idm.main` from source."""
    if getattr(sys, "frozen", False):
        exe = os.path.join(os.path.dirname(sys.executable), "Lavati Downloader.exe")
        return [exe, "--background"] if os.path.exists(exe) else None
    return [sys.executable, "-m", "idm.main", "--background"]


def relay(message: dict, launch: bool = True) -> dict:
    try:
        return send_request(message)
    except NotRunning:
        if not launch:
            return {"ok": False, "error": "Lavati Downloader is not running"}
    command = app_command()
    if command is None:
        return {"ok": False, "error": "Lavati Downloader is not installed next to the browser host"}
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(command, creationflags=flags, close_fds=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        time.sleep(0.4)
        try:
            return send_request(message)
        except NotRunning:
            continue
    return {"ok": False, "error": "Lavati Downloader did not start in time"}


def main() -> int:
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    while True:
        try:
            message = read_message(stdin)
        except (ValueError, struct.error):
            return 1
        if message is None:
            return 0
        # only "config" polls must not start the app; adding a download should
        reply = relay(message, launch=message.get("type") == "add")
        write_message(stdout, reply)


if __name__ == "__main__":
    raise SystemExit(main())
