from __future__ import annotations

import threading
import time


class SpeedLimiter:
    """Thread-safe token bucket. `rate_bytes_per_sec=None` means unlimited.

    A single instance can be shared across many concurrent readers (e.g. all
    segments of one download, or every active download for a global cap);
    each call to consume() blocks the calling thread only as long as needed
    to stay under the configured rate.
    """

    def __init__(self, rate_bytes_per_sec: int | None = None):
        self._lock = threading.Lock()
        self._rate = rate_bytes_per_sec if rate_bytes_per_sec and rate_bytes_per_sec > 0 else None
        self._tokens = float(self._rate or 0)
        self._last_refill = time.monotonic()

    @property
    def rate_bytes_per_sec(self) -> int | None:
        return self._rate

    def set_rate(self, rate_bytes_per_sec: int | None) -> None:
        with self._lock:
            self._rate = (
                rate_bytes_per_sec if rate_bytes_per_sec and rate_bytes_per_sec > 0 else None
            )
            self._tokens = float(self._rate or 0)
            self._last_refill = time.monotonic()

    def consume(self, num_bytes: int) -> None:
        """Block until `num_bytes` worth of budget is available."""
        if self._rate is None or num_bytes <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._last_refill = now
                self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
                if self._tokens >= num_bytes:
                    self._tokens -= num_bytes
                    return
                deficit = num_bytes - self._tokens
                wait_time = deficit / self._rate
            time.sleep(min(wait_time, 0.5))


class ChainedSpeedLimiter:
    """Consumes from several limiters in sequence (e.g. per-download + global cap)."""

    def __init__(self, *limiters: SpeedLimiter):
        self._limiters = limiters

    def consume(self, num_bytes: int) -> None:
        for limiter in self._limiters:
            limiter.consume(num_bytes)
