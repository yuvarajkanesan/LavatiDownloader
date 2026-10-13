from idm.core.clipboard_detect import extract_first_url, looks_like_download_url


def test_detects_direct_file_link():
    assert looks_like_download_url("check this out https://example.com/movie.mp4 nice")


def test_ignores_plain_page_link():
    assert not looks_like_download_url("https://example.com/blog/post-about-cats")


def test_ignores_non_url_text():
    assert not looks_like_download_url("just some text, no links here")


def test_query_string_after_extension_still_detected():
    assert looks_like_download_url("https://cdn.example.com/file.zip?token=abc123")


def test_extract_first_url():
    assert extract_first_url("go to https://a.com/x.zip please") == "https://a.com/x.zip"
    assert extract_first_url("no url here") is None
