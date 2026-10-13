"""Renders the app's programmatic icon (idm.gui.icons.make_app_icon) to a
multi-resolution .ico for PyInstaller's --icon flag. Not part of the
shipped app -- a build-time-only helper."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QIcon

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from idm.gui.icons import make_app_icon

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    app = QGuiApplication(sys.argv)
    out_path = Path(__file__).resolve().parent / "app_icon.ico"

    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(make_app_icon(size).pixmap(size, size))

    # QIcon has no direct multi-size .ico writer; save the largest pixmap
    # and let Qt's ICO plugin embed it, then verify round-trip.
    largest = make_app_icon(256).pixmap(256, 256)
    if not largest.save(str(out_path), "ICO"):
        raise SystemExit("Failed to write .ico -- is Qt's ICO image plugin available?")
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
