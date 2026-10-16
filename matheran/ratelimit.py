"""Async token buckets so we stay inside broker rate limits.

Dhan v2 published limits: order 10/s, data 5/s, quote 1/s, non-trading 20/s.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from typing import Iterable


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


class RequestLedger:
    """HTTP requests made by this process to one provider, by tag, over a rolling horizon.

    Tags are free text such as "app" (engine, charts) or "scanner:<job id>"; a prefix
    query for "scanner" matches every "scanner:*" tag. Requests made by other
    processes (from the scanner's ledger file) can be merged in with set_external.

    Not thread-safe, on purpose: every method must be called on the event-loop
    thread only. Worker threads receive and return plain lists (epochs()), never this
    object, so the deque is never iterated or rebuilt while the loop appends to it.
    """

    EXTERNAL_TAG = "scanner:ext"

    def __init__(self, horizon_seconds: float = 1800.0):
        self.horizon = float(horizon_seconds)
        self._events: deque[tuple[float, str]] = deque()   # (monotonic time, tag), in order
        self._totals: dict[str, int] = {}
        # One offset converts between monotonic and wall-clock (epoch) seconds.
        self._offset = time.time() - time.monotonic()

    def _prune(self, now: float) -> None:
        cutoff = now - self.horizon
        events = self._events
        while events and events[0][0] < cutoff:
            events.popleft()

    @staticmethod
    def _matches(tag: str, prefix: str | None) -> bool:
        return prefix is None or tag == prefix or tag.startswith(prefix + ":")

    def record(self, tag: str = "app") -> None:
        now = time.monotonic()
        self._events.append((now, tag))
        self._totals[tag] = self._totals.get(tag, 0) + 1
        self._prune(now)

    def count(self, seconds: float, prefix: str | None = None) -> int:
        """Requests within the last `seconds` whose tag matches `prefix` (all if None)."""
        now = time.monotonic()
        self._prune(now)
        cutoff = now - float(seconds)
        n = 0
        for ts, tag in reversed(self._events):
            if ts < cutoff:
                break
            if self._matches(tag, prefix):
                n += 1
        return n

    def total(self, tag: str) -> int:
        """Lifetime count for one exact tag; never pruned."""
        return self._totals.get(tag, 0)

    def free_in(
        self, seconds: float, limit: int, need: int = 1, prefix: str | None = None
    ) -> float:
        """Seconds until count(seconds, prefix) + need <= limit; 0.0 if already true,
        math.inf when need > limit (only requests landing elsewhere could change that)."""
        if need > limit:
            return math.inf
        now = time.monotonic()
        self._prune(now)
        cutoff = now - float(seconds)
        matching = [ts for ts, tag in self._events if ts >= cutoff and self._matches(tag, prefix)]
        excess = len(matching) + need - limit
        if excess <= 0:
            return 0.0
        # The excess-th oldest matching request must age out of the window.
        return max(0.0, matching[excess - 1] + float(seconds) - now)

    def set_external(self, epochs: Iterable[float], tag: str = EXTERNAL_TAG) -> None:
        """Replace the entries of `tag` with requests made by other processes, given as
        wall-clock epoch seconds. Idempotent: loading the same list twice counts once."""
        now = time.monotonic()
        cutoff = now - self.horizon
        external = sorted(
            float(e) - self._offset for e in epochs if float(e) - self._offset >= cutoff
        )
        own = [ev for ev in self._events if ev[1] != tag]
        merged = sorted(own + [(ts, tag) for ts in external], key=lambda ev: ev[0])
        self._events = deque(merged)
        self._prune(now)

    def epochs(
        self, seconds: float, prefix: str | None = None, *, external: bool = False
    ) -> list[float]:
        """Wall-clock epoch seconds of the matching requests within `seconds`. The
        external entries are left out unless external=True, so a process never
        re-exports another process's requests as its own."""
        now = time.monotonic()
        self._prune(now)
        cutoff = now - float(seconds)
        return [
            ts + self._offset
            for ts, tag in self._events
            if ts >= cutoff
            and self._matches(tag, prefix)
            and (external or tag != self.EXTERNAL_TAG)
        ]


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
