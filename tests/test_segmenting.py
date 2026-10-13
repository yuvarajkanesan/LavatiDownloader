from idm.core.task import plan_segments


def test_even_split():
    segments = plan_segments(download_id=1, total_size=1000, connections=4)
    assert len(segments) == 4
    assert [s.start_byte for s in segments] == [0, 250, 500, 750]
    assert [s.end_byte for s in segments] == [249, 499, 749, 999]
    # contiguous, no gaps or overlaps, covers the whole file
    assert segments[0].start_byte == 0
    assert segments[-1].end_byte == 999
    for a, b in zip(segments, segments[1:]):
        assert b.start_byte == a.end_byte + 1


def test_uneven_split_last_segment_absorbs_remainder():
    segments = plan_segments(download_id=1, total_size=1001, connections=4)
    assert len(segments) == 4
    total_covered = sum(s.end_byte - s.start_byte + 1 for s in segments)
    assert total_covered == 1001
    assert segments[-1].end_byte == 1000


def test_more_connections_than_bytes_clamped():
    segments = plan_segments(download_id=1, total_size=3, connections=8)
    assert len(segments) == 3
    total_covered = sum(s.end_byte - s.start_byte + 1 for s in segments)
    assert total_covered == 3


def test_single_connection():
    segments = plan_segments(download_id=1, total_size=500, connections=1)
    assert len(segments) == 1
    assert segments[0].start_byte == 0
    assert segments[0].end_byte == 499


def test_unknown_size_yields_single_open_ended_segment():
    segments = plan_segments(download_id=1, total_size=-1, connections=8)
    assert len(segments) == 1
    assert segments[0].start_byte == 0
    assert segments[0].end_byte == -1
    assert segments[0].size_unknown is True
