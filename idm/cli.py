"""Headless harness for exercising the download engine without the GUI.

Usage:
    python -m idm.cli <url> [destination_dir]
"""

from __future__ import annotations

import sys
import time

from idm.storage.db import Database
from idm.storage.models import DownloadStatus
from idm.storage.paths import default_database_path, default_downloads_root
from idm.storage.repository import DownloadRepository
from idm.core.errors import DuplicateDownloadError
from idm.core.queue_manager import DownloadManager


def _format_bytes(n: int) -> str:
    if n < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    url = sys.argv[1]
    dest_dir = sys.argv[2] if len(sys.argv) > 2 else None

    db = Database(default_database_path())
    repo = DownloadRepository(db)
    manager = DownloadManager(repo, downloads_root=default_downloads_root(), max_concurrent=3)

    def on_event(event):
        pct = f"{event.progress_fraction * 100:5.1f}%" if event.progress_fraction is not None else " ?  %"
        print(
            f"\r[{event.status.value:>11}] {pct} "
            f"{_format_bytes(event.downloaded_bytes)}/{_format_bytes(event.total_size)} "
            f"@ {_format_bytes(int(event.speed_bytes_per_sec))}/s   ",
            end="", flush=True,
        )

    manager.add_listener(on_event)
    try:
        record = manager.add_download(url, destination_dir=dest_dir)
    except DuplicateDownloadError as exc:
        print(
            f"Already queued as download {exc.existing.id} "
            f"({exc.existing.status.value}): {exc.existing.destination_path}"
        )
        db.close()
        return 1
    print(f"Queued download {record.id}: {record.url} -> {record.destination_path}")

    exit_code = 0
    while True:
        time.sleep(0.3)
        current = repo.get_download(record.id)
        if current.status in (
            DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELED,
        ):
            print()
            print(f"Final status: {current.status.value}")
            if current.error_message:
                print(f"Error: {current.error_message}")
            exit_code = 0 if current.status == DownloadStatus.COMPLETED else 1
            break

    db.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
