from pathlib import Path

from idm.storage.paths import category_folder, category_for_extension


def test_category_folder_accepts_path_root(tmp_path):
    folder = category_folder(tmp_path, "Documents")
    assert folder == tmp_path / "Documents"
    assert folder.is_dir()


def test_category_folder_accepts_string_root(tmp_path):
    # A user-configured "default download folder" setting round-trips
    # through SQLite as plain text; category_folder() must accept that
    # directly rather than requiring the caller to wrap it in Path() first.
    folder = category_folder(str(tmp_path), "Music")
    assert folder == tmp_path / "Music"
    assert folder.is_dir()


def test_category_folder_falls_back_to_other_for_unknown_category(tmp_path):
    folder = category_folder(tmp_path, "Nonexistent")
    assert folder == tmp_path / "Other"


def test_category_for_extension_known_and_unknown():
    assert category_for_extension("movie.mp4") == "Video"
    assert category_for_extension("archive.zip") == "Compressed"
    assert category_for_extension("mystery.xyz") == "Other"
