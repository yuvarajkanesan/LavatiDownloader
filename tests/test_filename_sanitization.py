"""Regression tests for the path-traversal / arbitrary-file-write fix.

A Content-Disposition header is server-controlled -- a malicious or
MITM'd server could set filename="../../Startup/evil.exe" or an absolute
path, aiming to write outside the user's chosen download folder (or ignore
it entirely, since os.path.join() drops its first argument when the second
is absolute). sanitize_filename() is the fix; these tests pin the behavior
at both the derivation point (filename_for) and the enforcement point
(DownloadManager.add_download) so neither can silently regress.
"""

import os

import pytest

from idm.core.http import filename_for
from idm.core.queue_manager import DownloadManager
from idm.storage.db import Database
from idm.storage.paths import sanitize_filename
from idm.storage.repository import DownloadRepository


# -- sanitize_filename() unit tests -----------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("report.pdf", "report.pdf"),
    ("../../../../Startup/evil.exe", "evil.exe"),
    ("..\\..\\Windows\\System32\\evil.dll", "evil.dll"),
    ("C:\\Windows\\System32\\evil.dll", "evil.dll"),
    ("/etc/passwd", "passwd"),
    ("..", "download"),
    ("...", "download"),
    ("", "download"),
    (None, "download"),
    ('file<>:"|?*.txt', "file_______.txt"),  # 7 unsafe chars -> 7 underscores
])
def test_sanitize_filename_strips_traversal_and_unsafe_chars(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_rejects_windows_reserved_device_names():
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("con.txt") == "_con.txt"
    assert sanitize_filename("COM1.exe") == "_COM1.exe"
    # Not a reserved name merely for containing one as a substring
    assert sanitize_filename("CONFIG.txt") == "CONFIG.txt"


def test_sanitize_filename_truncates_overlong_names_but_keeps_extension():
    long_name = "a" * 300 + ".txt"
    result = sanitize_filename(long_name)
    assert len(result) <= 255
    assert result.endswith(".txt")


def test_sanitize_filename_strips_trailing_dots_and_spaces():
    # Windows treats "name." / "name " specially; strip() covers both.
    assert sanitize_filename("evil.") == "evil"
    assert sanitize_filename("evil ") == "evil"


# -- filename_for() derives an already-safe name -----------------------------

def test_filename_for_sanitizes_malicious_content_disposition():
    header = 'attachment; filename="../../../../Startup/evil.exe"'
    result = filename_for("https://example.com/download?id=1", header)
    assert result == "evil.exe"
    assert ".." not in result
    assert "/" not in result and "\\" not in result


def test_filename_for_sanitizes_absolute_path_in_content_disposition():
    header = 'attachment; filename="C:\\Windows\\System32\\evil.dll"'
    result = filename_for("https://example.com/download", header)
    assert result == "evil.dll"


# -- DownloadManager.add_download() is the enforcement boundary -------------

@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    yield DownloadRepository(db)
    db.close()


def test_add_download_confines_malicious_filename_to_chosen_folder(tmp_path, repo):
    manager = DownloadManager(repo, downloads_root=tmp_path, max_concurrent=1)
    dest_dir = tmp_path / "chosen"
    dest_dir.mkdir()

    record = manager.add_download(
        "https://example.com/x",
        destination_dir=str(dest_dir),
        filename="../../../../etc/passwd",
        start_immediately=False,
    )

    resolved = os.path.normpath(record.destination_path)
    assert resolved.startswith(os.path.normpath(str(dest_dir)))
    assert os.path.dirname(resolved) == os.path.normpath(str(dest_dir))
    assert os.path.basename(resolved) == "passwd"


def test_add_download_confines_absolute_windows_path_filename(tmp_path, repo):
    manager = DownloadManager(repo, downloads_root=tmp_path, max_concurrent=1)
    dest_dir = tmp_path / "chosen"
    dest_dir.mkdir()

    record = manager.add_download(
        "https://example.com/x",
        destination_dir=str(dest_dir),
        # Without sanitization, os.path.join(dest_dir, this) would discard
        # dest_dir entirely and resolve to the attacker-chosen absolute path.
        filename="C:\\Windows\\System32\\drivers\\etc\\hosts",
        start_immediately=False,
    )

    resolved = os.path.normpath(record.destination_path)
    assert os.path.dirname(resolved) == os.path.normpath(str(dest_dir))
    assert os.path.basename(resolved) == "hosts"
