import re

import pytest
from PySide6.QtWidgets import QApplication

FILE_CONTENT = b"0123456789" * 250  # 2500 bytes


@pytest.fixture(scope="session")
def qapp():
    """Only one QApplication may exist per process, so this is session-scoped
    and shared by every GUI test that needs a real (not mocked) Qt event loop."""
    app = QApplication.instance() or QApplication([])
    yield app


def range_serving_callback(content: bytes = FILE_CONTENT, on_get=None):
    """Build a `responses.add_callback` handler that serves HEAD (metadata
    only) and GET (honoring a Range header, or the full body without one)
    against an in-memory byte string, mimicking a real Range-capable server.
    """

    def callback(request):
        if on_get is not None and request.method == "GET":
            on_get(request)

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Type": "application/octet-stream",
        }
        if request.method == "HEAD":
            headers["Content-Length"] = str(len(content))
            return (200, headers, b"")

        range_header = request.headers.get("Range")
        if range_header:
            match = re.match(r"bytes=(\d+)-(\d+)", range_header)
            start, end = int(match.group(1)), int(match.group(2))
            end = min(end, len(content) - 1)
            body = content[start:end + 1]
            headers["Content-Range"] = f"bytes {start}-{end}/{len(content)}"
            headers["Content-Length"] = str(len(body))
            return (206, headers, body)

        headers["Content-Length"] = str(len(content))
        return (200, headers, content)

    return callback
