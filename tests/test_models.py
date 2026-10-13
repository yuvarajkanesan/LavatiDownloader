from idm.storage.models import SegmentRecord


def test_known_size_segment_completion():
    seg = SegmentRecord(id=1, download_id=1, index=0, start_byte=0, end_byte=99)
    assert not seg.is_complete
    assert seg.remaining_bytes == 100
    seg.downloaded_bytes = 100
    assert seg.is_complete
    assert seg.remaining_bytes == 0


def test_unknown_size_segment_never_reports_complete_by_byte_count():
    seg = SegmentRecord(id=1, download_id=1, index=0, start_byte=0, end_byte=-1)
    assert seg.size_unknown
    assert seg.remaining_bytes is None
    # Even with zero bytes downloaded it must not look "already complete" --
    # this was a real bug: the naive formula treated end_byte=-1 as a
    # 0-length range and download_segment skipped the download entirely.
    assert seg.is_complete is False
    seg.downloaded_bytes = 5000
    assert seg.is_complete is False
