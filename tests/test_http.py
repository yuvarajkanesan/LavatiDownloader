from idm.core.http import filename_for


def test_filename_from_url_when_no_content_disposition():
    assert filename_for("https://example.com/path/report.pdf", None) == "report.pdf"


def test_filename_from_url_percent_encoded():
    assert filename_for("https://example.com/my%20file.zip", None) == "my file.zip"


def test_filename_from_content_disposition_basic():
    header = 'attachment; filename="archive.zip"'
    assert filename_for("https://example.com/download?id=1", header) == "archive.zip"


def test_filename_from_content_disposition_rfc5987_star():
    header = "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf"
    assert filename_for("https://example.com/download", header) == "résumé.pdf"


def test_filename_falls_back_to_download_for_root_path():
    assert filename_for("https://example.com/", None) == "download"
