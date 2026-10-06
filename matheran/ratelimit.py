"""Async token buckets so we stay inside broker rate limits.

Dhan v2 published limits: order 10/s, data 5/s, quote 1/s, non-trading 20/s.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: float | None = None, name: str = ""):
        self.rate = float(rate_per_sec)
        self.capacity = float(burst if burst is not None else max(1.0, rate_per_sec))
        self.name = name
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                await asyncio.sleep(max(deficit / self.rate, 0.01))


class DailyQuota:
    """Simple per-day counter so a runaway loop cannot burn the daily allowance."""

    def __init__(self, limit: int, name: str = ""):
        self.limit = limit
        self.name = name
        self._day: str = ""
        self._count = 0

    def check_and_increment(self, day: str, amount: int = 1) -> bool:
        if day != self._day:
            self._day = day
            self._count = 0
        if self._count + amount > self.limit:
            return False
        self._count += amount
        return True

    @property
    def used(self) -> int:
        return self._count
