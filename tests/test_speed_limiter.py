import time

from idm.core.speed_limiter import ChainedSpeedLimiter, SpeedLimiter


def test_unlimited_does_not_block():
    limiter = SpeedLimiter(None)
    start = time.monotonic()
    limiter.consume(10_000_000)
    assert time.monotonic() - start < 0.1


def test_rate_limit_throttles_bursts():
    limiter = SpeedLimiter(rate_bytes_per_sec=1000)
    limiter.consume(1000)  # drains the initial full bucket instantly
    start = time.monotonic()
    limiter.consume(500)  # must now wait ~0.5s for refill
    elapsed = time.monotonic() - start
    assert elapsed >= 0.4


def test_set_rate_can_disable_limit():
    limiter = SpeedLimiter(rate_bytes_per_sec=1)
    limiter.set_rate(None)
    start = time.monotonic()
    limiter.consume(10_000_000)
    assert time.monotonic() - start < 0.1


def test_chained_limiter_consumes_from_all():
    calls = []

    class Recorder:
        def consume(self, n):
            calls.append(n)

    chained = ChainedSpeedLimiter(Recorder(), Recorder())
    chained.consume(42)
    assert calls == [42, 42]
