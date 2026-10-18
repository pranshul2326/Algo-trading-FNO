"""The scanner's data layer: targets, the disk history cache, the request budget,
live quotes, the one-scan-at-a-time lock and the fetching feed.

Read-only by construction: nothing here places orders, creates watches or calls a
broker's ltp() (PaperBroker.ltp settles simulated resting orders). Live prices come
from QuoteBook, which calls quote_ltp on the data node itself.

Every file-system method (HistoryCache, RunLock, LedgerFile) is either awaited
through asyncio.to_thread by its caller or does that itself, so no job step reads or
stats a file on the event loop.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import math
import os
import re
import shutil
import time as _time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, TypeVar

from .brokers import Broker, BrokerError, UpstoxData
from .brokers.upstox import EQUITY_TYPES, REQUEST_COUNTER, request_pieces
from .candles import DAY, Candle, CandleSeries
from .models import Instrument
from .ratelimit import RequestLedger, TokenBucket
from .timeutil import IST, mcx_close_time, now_ist, session_open
from .universes import (
    DERIVED_SOURCE,
    DERIVED_UNIVERSES,
    INDEX_UNIVERSES,
    UNIVERSE_IDS,
    UniverseStore,
)

if TYPE_CHECKING:  # pragma: no cover
    from .scanner import Plan, ScanSpec, Source

log = logging.getLogger(__name__)
T = TypeVar("T")

MAX_TARGETS = 1000


# ------------------------------------------------------------------ errors
class ScanBusy(Exception):
    """A scan is already running, in this process or in another one (API 409, CLI exit 1).
    Defined here (re-exported by scanner.py) so RunLock can raise it without a cycle."""


class ScanCancelled(Exception):
    """The scan was cancelled while a call waited for request tokens.

    Deliberately NOT a BrokerError: a cancelled wait is neither a data error nor a
    symbol error. ScanFeed._fetch and QuoteBook let it pass untouched, and the ScanJob
    worker catches it ahead of BrokerError and returns with no result for the symbol.
    """


class BrokerSwapped(Exception):
    """engine.broker changed during the scan (the console's "Apply to engine")."""


class DataPathStopped(Exception):
    """NSE targets are no longer dispatched: the first min(3, N) NSE today fetches on a
    non-Upstox data path failed with one message that names none of their symbols (F14).
    Not a BrokerError: the symbol gets no result (no request was made for it)."""


class _TodayWatch:
    """F14: the first `n` NSE today fetches of a scan on a non-Upstox data path. The
    other NSE fetches wait for the verdict; a success or a retryable error clears it."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.started = 0
        self.failures: list[tuple[str, str]] = []   # (symbol, message)
        self.decided = asyncio.Event()
        self.stopped: str | None = None
        self.dropped = 0

    def clear(self) -> None:
        self.decided.set()

    def record(self, symbol: str, exc: BrokerError) -> None:
        if self.decided.is_set():
            return
        if exc.retryable:
            self.clear()
            return
        self.failures.append((symbol, str(exc)))
        if len(self.failures) < self.n:
            return
        msg = self.failures[0][1]
        if (all(m == msg for _s, m in self.failures)
                and not any(s in msg for s, _m in self.failures)):
            self.stopped = msg
        self.clear()


# ----------------------------------------------------------------- targets
@dataclass(slots=True)
class Target:
    instrument: Instrument   # carries data_key whenever it came from an Upstox master
    exchange: str            # "NSE" | "BSE" | "MCX"
    symbol: str              # RELIANCE, GOLD
    name: str                # company name, or the contract e.g. "GOLD FUT 04 DEC 26"
    chart_symbol: str        # eq:NSE:RELIANCE | eq:BSE:RELIANCE | mcx:GOLD
    tradable: bool           # the Watch action: True for every NSE/BSE target resolved by
                             # symbol, whatever its instrument_type (EQ/BE on Upstox, EQUITY on
                             # Dhan and synthetic); only ISIN hits use instrument_type in
                             # EQUITY_TYPES; False for MCX
    chartable: bool          # the Chart action: the same rule, but True for MCX
    origins: list[str]       # universe ids and/or "custom"
    key: str                 # dedupe key, unique per instrument
    provider: str            # "upstox" | "dhan" | "synthetic" | "other"
    source: str              # data_source_name of the node serving its candles
    notes: list[str] = field(default_factory=list)   # per-symbol notes from expansion


@dataclass(slots=True)
class Expansion:
    targets: list[Target]
    universes: list[dict]
    notes: list[str]
    skipped: list[dict]


KNOWN_PROVIDERS = ("upstox", "dhan", "synthetic")


def data_source_name(node: Broker) -> str:
    """Who serves this node's candles, named as the rest of the app names it."""
    return getattr(node, "data_source", node.name)


def provider_of(node: Broker) -> str:
    """The budget and quote class: "upstox", "dhan" or "synthetic", else "other"."""
    name = data_source_name(node)
    return name if name in KNOWN_PROVIDERS else "other"


def target_key(inst: Instrument, provider: str) -> str:
    if inst.data_key:
        return inst.data_key
    if provider == "synthetic":
        return f"{inst.segment}:{inst.symbol.upper()}"
    return f"{inst.segment}:{inst.security_id}"


def _short_day(d: date) -> str:
    return f"{d.day} {d:%b}"


# ------------------------------------------------------------ history cache
HISTORY_PUBLISHED_BY = time(9, 0)   # IST: by then Upstox has the previous session
PROVISIONAL_TTL = 1800.0            # seconds a window that lacks its last session may be reused


def all_day(complete: bool, fetched_at: datetime, day: date) -> bool:
    """Reusable for the rest of `day`: it has its last session, or it was fetched when that
    session must already have been published (still missing then = a holiday or no trades)."""
    return complete or fetched_at >= datetime.combine(day, HISTORY_PUBLISHED_BY, tzinfo=IST)


def entry_usable(complete: bool, fetched_at: datetime, now: datetime, day: date) -> bool:
    """The whole reuse rule, pure. A provisional entry is reused for at most
    PROVISIONAL_TTL and never at or after HISTORY_PUBLISHED_BY."""
    if all_day(complete, fetched_at, day):
        return True
    cutoff = datetime.combine(day, HISTORY_PUBLISHED_BY, tzinfo=IST)
    return now < cutoff and (now - fetched_at).total_seconds() < PROVISIONAL_TTL


_DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _series_to_rows(series: CandleSeries) -> list[list]:
    return [[c.ts.timestamp(), c.open, c.high, c.low, c.close, c.volume, c.oi]
            for c in series.candles]


def _rows_to_series(rows) -> CandleSeries:
    out = []
    for r in rows:
        out.append(Candle(ts=datetime.fromtimestamp(float(r[0]), IST), open=float(r[1]),
                          high=float(r[2]), low=float(r[3]), close=float(r[4]),
                          volume=float(r[5]), oi=float(r[6])))
    return CandleSeries(out)


class HistoryCache:
    """Prior-session windows on disk, per IST day: cache_dir/scan/<day>/<hash>.json.gz
    (reusable all day) or <hash>.prov.json.gz (provisional, see entry_usable)."""

    def __init__(self, root: Path, day: date, clock: Callable[[], datetime] = now_ist) -> None:
        self.root = Path(root)
        self.day = day
        self.clock = clock
        self.dir = self.root / day.isoformat()
        self.hits = 0
        self.misses = 0
        self._warned_write = False
        self._warned_prune = False

    def _paths(self, key: str) -> tuple[Path, Path]:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:32]
        return self.dir / f"{h}.json.gz", self.dir / f"{h}.prov.json.gz"

    @staticmethod
    def _read(path: Path, key: str) -> dict | None:
        """The entry at path, None if missing; a corrupt file is deleted (a miss)."""
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.debug("scan cache: cannot read %s (%s)", path.name, exc)
            return None
        try:
            doc = json.loads(gzip.decompress(raw).decode("utf-8"))
            if not isinstance(doc, dict) or doc.get("v") != 1 or doc.get("key") != key:
                raise ValueError("version or key mismatch")
            doc["_fetched_at"] = datetime.fromisoformat(str(doc["fetched_at"]))
            doc["_series"] = _rows_to_series(doc.get("candles") or [])
            return doc
        except (OSError, ValueError, KeyError, TypeError, IndexError, EOFError) as exc:
            log.debug("scan cache: dropping corrupt %s (%s)", path.name, exc)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def _get_sync(self, key: str) -> CandleSeries | None:
        full, prov = self._paths(key)
        doc = self._read(full, key)
        if doc is not None:
            return doc["_series"]
        doc = self._read(prov, key)
        if doc is not None and entry_usable(False, doc["_fetched_at"], self.clock(), self.day):
            return doc["_series"]
        return None

    async def get(self, key: str) -> CandleSeries | None:
        series = await asyncio.to_thread(self._get_sync, key)
        if series is None:
            self.misses += 1
        else:
            self.hits += 1
        return series

    def _put_sync(self, key: str, series: CandleSeries, end: date, fetched_at: datetime) -> bool:
        last = series.last
        complete = bool(last is not None and last.ts.date() == end)
        full, prov = self._paths(key)
        target = full if all_day(complete, fetched_at, self.day) else prov
        doc = {"v": 1, "key": key, "end": end.isoformat(), "complete": complete,
               "fetched_at": fetched_at.isoformat(), "candles": _series_to_rows(series)}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            try:
                tmp.write_bytes(gzip.compress(json.dumps(doc, separators=(",", ":")).encode()))
                os.replace(tmp, target)
            finally:
                tmp.unlink(missing_ok=True)
            if target is full:
                prov.unlink(missing_ok=True)
        except OSError as exc:
            if not self._warned_write:
                self._warned_write = True
                log.warning("scanner: cannot write the history cache in %s (%s); "
                            "this scan continues uncached", self.dir, exc)
        return complete

    async def put(self, key: str, series: CandleSeries, *, end: date) -> bool:
        return await asyncio.to_thread(self._put_sync, key, series, end, self.clock())

    def _prune_sync(self) -> None:
        keep = {self.day.isoformat(), (self.day - timedelta(days=1)).isoformat()}
        try:
            entries = list(self.root.iterdir())
        except FileNotFoundError:
            return
        except OSError as exc:
            self._warn_prune(exc)
            return
        for entry in entries:
            if not _DAY_DIR.match(entry.name) or entry.name in keep:
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
            except OSError as exc:   # best effort, per directory (F7)
                self._warn_prune(exc)

    def _warn_prune(self, exc: OSError) -> None:
        if not self._warned_prune:
            self._warned_prune = True
            log.warning("scanner: could not prune old history-cache days in %s (%s)",
                        self.root, exc)

    async def prune(self) -> None:
        await asyncio.to_thread(self._prune_sync)

    def exists_many(self, keys: list[str]) -> set[str]:
        """Synchronous: the keys that have an all-day entry (never a provisional one).
        The caller runs it in one asyncio.to_thread call."""
        return {k for k in keys if self._paths(k)[0].exists()}


# ------------------------------------------------------------------ budget
WINDOW = 1800.0                      # seconds: Upstox's 30-minute window


def available_now(ledger: RequestLedger, *, scanner_cap: int, total_cap: int = 1850,
                  in_flight: int = 0, window: float = WINDOW) -> int:
    """Upstox requests the scanner may send now without waiting:
    min(scanner_cap - scanner requests in the window (this process and other processes
    through set_external), total_cap - all requests in the window) - in_flight, >= 0.
    Event loop only (it reads the ledger)."""
    free = min(scanner_cap - ledger.count(window, prefix="scanner"),
               total_cap - ledger.count(window))
    return max(0, int(free) - int(in_flight))


def eta_seconds(requests: int, *, rate: float, cap: int, ages: list[float],
                window: float = WINDOW) -> float:
    """Seconds to send `requests` more requests at `rate` per second without more than
    `cap` of the scanner's requests in any `window`; `ages` = how many seconds ago each
    request already counted against the cap was made. Pure simulation, O(requests)."""
    if requests <= 0:
        return 0.0
    step = 1.0 / max(rate, 1e-9)
    times: deque[float] = deque(sorted(-float(a) for a in ages if float(a) < window))
    t = -step
    for _ in range(int(requests)):
        t = max(t + step, 0.0)
        while times and times[0] <= t - window:
            times.popleft()
        if cap > 0 and len(times) >= cap:
            t = times[len(times) - cap] + window
            while times and times[0] <= t - window:
                times.popleft()
        times.append(t)
    return t


@dataclass(eq=False, slots=True)
class _Call:                         # one budgeted Upstox call in progress (identity-hashed)
    granted: int = 0                 # tokens reserved for it: 0 while waiting, then all n at once
    sent: list[int] = field(default_factory=lambda: [0])   # requests it has recorded


class Budget:
    """Request tokens for one scan. Upstox calls reserve all n tokens of a call in one
    synchronous step against the scanner cap (counting granted-but-unsent tokens), the
    30-minute total and the per-minute cap, then are paced by a token bucket. Dhan and
    "other" providers are only paced, by their own buckets."""

    PACED = ("dhan", "other")

    def __init__(self, ledger: RequestLedger, tag: str, *, rate: float, scanner_cap: int,
                 total_cap: int = 1850, minute_cap: int = 450, window_seconds: float = WINDOW,
                 on_wait: Callable[[float | None], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> None:
        self.ledger = ledger
        self.tag = tag
        self.rate = float(rate)
        self.scanner_cap = int(scanner_cap)
        self.total_cap = int(total_cap)
        self.minute_cap = int(minute_cap)
        self.window = float(window_seconds)
        self.on_wait = on_wait or (lambda _until: None)
        self.cancelled = cancelled or (lambda: False)
        slow = min(self.rate, 2.0)                              # half of Dhan's 4/s data bucket
        self._normal = {"upstox": self.rate, "dhan": slow, "other": slow}
        self.buckets = {"upstox": TokenBucket(self.rate, burst=max(1.0, self.rate), name="scanner"),
                        "dhan": TokenBucket(slow, burst=max(1.0, slow), name="scanner-dhan"),
                        "other": TokenBucket(slow, burst=max(1.0, slow), name="scanner-other")}
        self.granted = {"upstox": 0, "dhan": 0, "other": 0}
        self._calls: set[_Call] = set()
        self._waiters: dict[_Call, float] = {}
        self._paused_until = {"upstox": 0.0, "dhan": 0.0, "other": 0.0}   # monotonic
        self._slow_until = {"upstox": 0.0, "dhan": 0.0, "other": 0.0}     # monotonic
        self._overspent_logged = False

    def in_flight(self) -> int:
        return sum(max(0, c.granted - c.sent[0]) for c in self._calls)

    def available(self) -> int:
        return available_now(self.ledger, scanner_cap=self.scanner_cap, total_cap=self.total_cap,
                             in_flight=self.in_flight(), window=self.window)

    def penalise_429(self, provider: str = "upstox") -> None:
        if provider not in self.buckets:
            return
        now = _time.monotonic()
        self._paused_until[provider] = now + 30.0
        self.buckets[provider].rate = self._normal[provider] / 2
        self._slow_until[provider] = now + 150.0

    def _restore(self, provider: str) -> None:
        until = self._slow_until[provider]
        if until and _time.monotonic() >= until:
            self.buckets[provider].rate = self._normal[provider]
            self._slow_until[provider] = 0.0

    def snapshot(self) -> dict:
        finite = [u for u in self._waiters.values() if math.isfinite(u)]
        return {
            "used_total_30m": self.ledger.count(self.window),
            "used_scanner_30m": self.ledger.count(self.window, prefix="scanner"),
            "used_60s": self.ledger.count(60),
            "in_flight": self.in_flight(),
            "caps": {"scanner_30m": self.scanner_cap, "total_30m": self.total_cap,
                     "per_minute": self.minute_cap},
            "rates": {k: b.rate for k, b in self.buckets.items()},
            "waiting": bool(self._waiters),
            "waiting_until": min(finite) if finite else None,
            "granted": dict(self.granted),
        }

    @asynccontextmanager
    async def spend(self, n: int, provider: str) -> AsyncIterator[None]:
        """Reserve n tokens for one broker call, pace them out, then run the body.
        Raises ScanCancelled as soon as the scan is cancelled while waiting."""
        n = max(1, int(n))
        if provider == "synthetic":
            yield
            return
        if provider not in self.buckets:
            raise ValueError(f"unknown provider {provider!r}")
        if provider in self.PACED:
            for _ in range(n):
                while True:
                    if self.cancelled():
                        raise ScanCancelled()
                    wait = self._paused_until[provider] - _time.monotonic()
                    if wait <= 0:
                        break
                    await asyncio.sleep(min(wait, 0.5))
                self._restore(provider)
                await self.buckets[provider].acquire(1)
                self.granted[provider] += 1
            yield
            return

        call = _Call()
        try:
            cap = min(self.scanner_cap, self.total_cap, self.minute_cap)
            if n > cap:   # could never be granted: fail at once, never wait
                raise BrokerError(f"this window needs {n} requests, more than the request cap "
                                  f"({cap}) allows", code="BUDGET")
            while True:
                if self.cancelled():
                    raise ScanCancelled()
                need = n + self.in_flight()
                w = max(self.ledger.free_in(self.window, self.scanner_cap, need, prefix="scanner"),
                        self.ledger.free_in(self.window, self.total_cap, need),
                        self.ledger.free_in(60, self.minute_cap, need),
                        self._paused_until["upstox"] - _time.monotonic())
                if w > 0:
                    self._waiters[call] = math.inf if math.isinf(w) else _time.time() + w
                    self.on_wait(min(self._waiters.values()))
                    # Short slices, so a cancel is noticed within half a second.
                    await asyncio.sleep(0.25 if math.isinf(w) else min(w, 0.5))
                    continue
                self._waiters.pop(call, None)
                self.on_wait(min(self._waiters.values(), default=None))
                # No await since the cap check: the reservation is atomic.
                call.granted = n
                self.granted["upstox"] += n
                self._calls.add(call)
                break
            for _ in range(n):            # pacing only; the reservation already counts
                self._restore("upstox")
                await self.buckets["upstox"].acquire(1)
            token = REQUEST_COUNTER.set(call.sent)
            try:
                yield
            finally:
                REQUEST_COUNTER.reset(token)
        finally:
            if self._waiters.pop(call, None) is not None:
                self.on_wait(min(self._waiters.values(), default=None))
            self._calls.discard(call)
            if call.sent[0] > call.granted and not self._overspent_logged:
                self._overspent_logged = True
                log.error("budget: %d requests on %d tokens", call.sent[0], call.granted)


# ------------------------------------------------------------------ quotes
@dataclass(eq=False, slots=True)
class _Batch:
    provider: str
    instruments: list[Instrument]
    keys: list[str]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    prices: dict[str, tuple[float | None, float, datetime]] = field(default_factory=dict)


class QuoteBook:
    """Live prices for one scan: budgeted, keyed exactly, from the provider that serves
    each symbol's candles. Never calls ltp() on any broker."""

    MAX_AGE = 30.0
    BATCH = {"upstox": 400, "dhan": 1000}

    def __init__(self, *, upstox: UpstoxData, dhan: Broker | None, budget: Budget,
                 clock: Callable[[], datetime], still_pinned: Callable[[], bool],
                 note: Callable[[str], None]) -> None:
        self.upstox = upstox
        self.dhan = dhan
        self.budget = budget
        self.clock = clock
        self.still_pinned = still_pinned
        self.note = note
        self.enabled = {"upstox": bool(upstox.access_token), "dhan": dhan is not None}
        self.requests = 0
        self._batch_of: dict[str, _Batch] = {}
        self._warned: set[str] = set()

    @staticmethod
    def quote_key(target: Target) -> str:
        inst = target.instrument
        if target.provider == "dhan":
            return f"{inst.segment}:{inst.security_id}"
        return inst.data_key or ""

    def plan(self, targets: list[Target]) -> None:
        upstox: dict[str, list[Target]] = {}
        dhan: list[Target] = []
        for t in targets:
            if t.provider == "upstox" and t.instrument.data_key:
                upstox.setdefault(t.instrument.segment, []).append(t)
            elif t.provider == "dhan":
                dhan.append(t)
        groups: list[tuple[str, list[Target]]] = []
        size = self.BATCH["upstox"]
        for rows in upstox.values():
            groups += [("upstox", rows[i:i + size]) for i in range(0, len(rows), size)]
        size = self.BATCH["dhan"]
        groups += [("dhan", dhan[i:i + size]) for i in range(0, len(dhan), size)]
        for provider, rows in groups:
            batch = _Batch(provider, [t.instrument for t in rows], [self.quote_key(t) for t in rows])
            for t in rows:
                self._batch_of[t.key] = batch

    def batches(self) -> int:
        """Quote batches of the planned targets whose provider gives quotes."""
        return len({id(b) for b in self._batch_of.values() if self.enabled.get(b.provider)})

    def fetched_at(self, target: Target) -> datetime | None:
        batch = self._batch_of.get(target.key)
        entry = batch.prices.get(self.quote_key(target)) if batch else None
        return entry[2] if entry else None

    def _warn(self, provider: str, message: str, note: str) -> None:
        if provider not in self._warned:
            self._warned.add(provider)
            log.warning(message)
            self.note(note)

    async def price(self, target: Target, last_bar_start: datetime) -> float | None:
        provider = target.provider
        if provider not in self.BATCH or not self.enabled.get(provider):
            return None
        batch = self._batch_of.get(target.key)
        if batch is None:
            return None
        qkey = self.quote_key(target)

        def fresh() -> bool:
            e = batch.prices.get(qkey)
            return e is not None and _time.monotonic() - e[1] <= self.MAX_AGE

        if not fresh():
            async with batch.lock:
                if not fresh() and self.enabled.get(provider):
                    if not self.still_pinned():
                        raise BrokerSwapped()
                    node = self.upstox if provider == "upstox" else self.dhan
                    try:
                        async with self.budget.spend(1, provider):
                            if not self.still_pinned():
                                raise BrokerSwapped()
                            self.requests += 1
                            prices = await node.quote_ltp(batch.instruments)
                    except BrokerError as exc:
                        self.enabled[provider] = False
                        if exc.status == 429 or exc.code == "DH-904":
                            self.budget.penalise_429(provider)
                        who = "Upstox" if provider == "upstox" else "Dhan"
                        self._warn(provider,
                                   f"{provider}: live quotes unavailable for this scan ({exc}); "
                                   "using candle closes",
                                   f"live quotes unavailable from {who}: {exc}; prices are the "
                                   "latest candle closes")
                        return None
                    mono, at = _time.monotonic(), self.clock()
                    for k in batch.keys:
                        batch.prices[k] = (prices.get(k), mono, at)
                    if not any(prices.get(k) for k in batch.keys):
                        self._warn(f"{provider}:empty",
                                   f"{provider}: a live-quote answer matched none of its "
                                   f"{len(batch.keys)} symbols; using candle closes (the quote "
                                   "format may have changed)",
                                   "live quotes returned no usable prices; using candle closes")
        entry = batch.prices.get(qkey)
        if entry is None or entry[0] is None:
            return None
        if entry[2] < last_bar_start:
            return None
        return entry[0]


# -------------------------------------------------------------- run lock
def _hhmmss(iso) -> str:
    try:
        return datetime.fromisoformat(str(iso)).astimezone(IST).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "?"


def busy_text(holder: dict) -> str:
    return (f"a scan is running in another Saidarshan process (pid {holder.get('pid')}, "
            f"started {_hhmmss(holder.get('started'))})")


class RunLock:
    """One scan at a time on this machine, across the server and the CLI:
    cache_dir/scan/.running, created with os.link so it is complete the moment it exists,
    refreshed every 2 s; older than STALE_AFTER means its holder died."""

    STALE_AFTER = 10.0

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._ino: int | None = None
        self._warned = False

    def acquire(self, job_id: str) -> None:
        """Synchronous (callers use asyncio.to_thread). Raises ScanBusy, or BrokerError
        (retryable) when the lock cannot be created at all."""
        folder = self.path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            now = _time.time()
            for old in folder.glob(".running.*.tmp"):
                try:
                    if now - old.stat().st_mtime > 60:
                        old.unlink(missing_ok=True)
                except OSError:
                    pass
            tmp = folder / f".running.{os.getpid()}.{job_id}.tmp"
            tmp.write_text(json.dumps({"pid": os.getpid(), "job": job_id,
                                       "started": now_ist().isoformat(timespec="seconds")}))
            try:
                self._link(tmp)
            finally:
                tmp.unlink(missing_ok=True)
        except ScanBusy:
            raise
        except OSError as exc:
            raise BrokerError(f"cannot create the scan lock in {folder}: {exc}",
                              retryable=True) from exc

    def _link(self, tmp: Path) -> None:
        missing_retry = stale_retry = False
        while True:
            try:
                os.link(tmp, self.path)
                self._ino = os.stat(self.path).st_ino
                return
            except FileExistsError:
                pass
            try:
                st = os.stat(self.path)
                try:
                    data = json.loads(self.path.read_text())
                except (ValueError, UnicodeDecodeError):
                    data = None
            except FileNotFoundError:
                if missing_retry:
                    raise ScanBusy("a scan lock was just taken by another process; try again")
                missing_retry = True
                continue
            pid = data.get("pid") if isinstance(data, dict) else None
            if pid == os.getpid() and self._ino is not None and st.st_ino == self._ino:
                # Our own lock, still held by a job of this process: live, not stale.
                raise ScanBusy("a scan is already running in this process")
            age = _time.time() - st.st_mtime
            if age <= self.STALE_AFTER and pid != os.getpid():
                if not isinstance(data, dict):
                    log.warning("scanner: the scan lock %s cannot be read", self.path)
                    raise ScanBusy("a scan lock exists but cannot be read; try again in 10 s")
                log.info("scanner: %s", busy_text(data))
                raise ScanBusy(busy_text(data))
            if stale_retry:   # another starter won the race
                holder = self.holder(self.path)
                raise ScanBusy(busy_text(holder) if holder else
                               "a scan lock was just taken by another process; try again")
            stale_retry = True
            try:
                if os.stat(self.path).st_ino == st.st_ino:
                    os.unlink(self.path)
                    log.info("removed a stale scan lock (pid %s)", pid)
            except FileNotFoundError:
                pass

    def _ours(self) -> bool:
        if self._ino is None:
            return False
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            st = None
        if st is None or st.st_ino != self._ino:
            if not self._warned:
                self._warned = True
                holder = self.holder(self.path) or {}
                log.warning("the scan lock was taken over by pid %s", holder.get("pid", "?"))
            return False
        return True

    def heartbeat(self) -> None:
        if self._ours():
            os.utime(self.path)

    def release(self) -> None:
        try:
            if self._ours():
                os.unlink(self.path)
        except OSError:
            pass
        self._ino = None

    @staticmethod
    def holder(path: Path) -> dict | None:
        """{"pid", "job", "started"} of a live lock (fresh and readable), else None."""
        try:
            st = os.stat(path)
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict) or _time.time() - st.st_mtime > RunLock.STALE_AFTER:
            return None
        return {"pid": data.get("pid"), "job": data.get("job"), "started": data.get("started")}


class LedgerFile:
    """Scanner requests of the last 30 minutes from every process: plain file I/O on
    plain lists, safe in a worker thread. {"v": 1, "entries": [[epoch, pid], ...]}."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._warned = False

    def _entries(self) -> list[list]:
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            log.debug("scan ledger: treating %s as empty (%s)", self.path.name, exc)
            return []
        if not isinstance(doc, dict) or doc.get("v") != 1 or not isinstance(doc.get("entries"), list):
            return []
        out = []
        for e in doc["entries"]:
            if (isinstance(e, list) and len(e) == 2 and isinstance(e[0], (int, float))
                    and isinstance(e[1], int)):
                out.append([float(e[0]), int(e[1])])
        return out

    def read_external(self) -> list[float]:
        cutoff = _time.time() - WINDOW
        me = os.getpid()
        return [e for e, pid in self._entries() if pid != me and e >= cutoff]

    def save(self, own_epochs: list[float]) -> None:
        cutoff = _time.time() - WINDOW
        me = os.getpid()
        entries = [[e, pid] for e, pid in self._entries() if pid != me and e >= cutoff]
        entries += [[float(e), me] for e in own_epochs if e >= cutoff]
        entries.sort()
        entries = entries[-2500:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # A unique name per call: a heartbeat save still in its thread must not share
            # the temp file with the final save.
            tmp = self.path.with_name(f".{self.path.name}.{me}.{os.urandom(4).hex()}.tmp")
            try:
                tmp.write_text(json.dumps({"v": 1, "entries": entries}))
                os.replace(tmp, self.path)
            finally:
                tmp.unlink(missing_ok=True)
        except OSError as exc:
            if not self._warned:
                self._warned = True
                log.warning("scanner: cannot save the request ledger %s (%s)", self.path, exc)


# -------------------------------------------------------------------- feed
class ScanFeed:
    """Targets, today's candles and history windows for one scan.

    broker: the pinned NSE data path (engine.broker at run start, or the CLI's broker).
    upstox: find_upstox(broker), else ScanManager's owned instance; BSE and MCX always go
    through it. today: the scan's IST date, pinned at start. clock: now_ist or an injected
    clock; every time decision of the scan reads it. still_pinned: False once engine.broker
    is no longer `broker`. note: adds a deduplicated note to the job. No I/O here.
    """

    def __init__(self, *, broker: Broker, upstox: UpstoxData, universes: UniverseStore,
                 cache: HistoryCache, budget: Budget, quotes: QuoteBook | None, today: date,
                 clock: Callable[[], datetime], still_pinned: Callable[[], bool],
                 note: Callable[[str], None]) -> None:
        self.broker = broker
        self.upstox = upstox
        self.universes = universes
        self.cache = cache
        self.budget = budget
        self.quotes = quotes
        self.day = today        # the scan's IST date (the today() method fetches its candles)
        self.clock = clock
        self.still_pinned = still_pinned
        self.note = note
        self.provider = provider_of(broker)
        self.source_name = data_source_name(broker)
        self.synthetic = self.provider == "synthetic"
        self.incomplete: dict[str, tuple[str, date]] = {}
        self.symbol_notes: dict[str, list[str]] = {}
        self.today_watch: _TodayWatch | None = None
        self._logged: set[str] = set()

    # ---- helpers ----
    def broker_for(self, target: Target) -> Broker:
        return self.broker if target.exchange == "NSE" else self.upstox

    def _once(self, key: str, level: int, msg: str, *args) -> None:
        if key not in self._logged:
            self._logged.add(key)
            log.log(level, msg, *args)

    def _check_pin(self) -> None:
        if not self.still_pinned():
            raise BrokerSwapped()

    def _symbol_note(self, target: Target, text: str) -> None:
        notes = self.symbol_notes.setdefault(target.key, [])
        if text not in notes:
            notes.append(text)

    def _target(self, inst: Instrument, exchange: str, *, name: str | None = None,
                origin: str, tradable: bool, chartable: bool, symbol: str | None = None,
                notes: list[str] | None = None) -> Target:
        node = self.broker if exchange == "NSE" else self.upstox
        provider = provider_of(node)
        sym = symbol or inst.symbol
        chart = f"mcx:{sym}" if exchange == "MCX" else f"eq:{exchange}:{sym}"
        return Target(instrument=inst, exchange=exchange, symbol=sym,
                      name=name or inst.display_name or sym, chart_symbol=chart,
                      tradable=tradable, chartable=chartable, origins=[origin],
                      key=target_key(inst, provider), provider=provider,
                      source=data_source_name(node), notes=list(notes or []))

    # ---- expansion ----
    async def expand(self, spec: "ScanSpec") -> Expansion:
        targets: list[Target] = []
        universes: list[dict] = []
        notes: list[str] = []
        skipped: list[dict] = []
        selected = set(spec.universes)
        index_ids = [u for u in UNIVERSE_IDS if u in selected and u in INDEX_UNIVERSES]
        custom_nse = [s for e, s in spec.custom if e == "NSE"]
        on_upstox = self.provider == "upstox"
        master = None

        if "fno" in selected or (on_upstox and (index_ids or custom_nse)):
            try:
                master = await self.upstox.exchange_instruments("NSE")
            except BrokerError as exc:
                raise BrokerError(str(exc), code=exc.code or "MASTER", retryable=True) from exc
        master_tried = master is not None

        async def isin_master():
            # On another data path the master only serves the ISIN fallback: loaded the
            # first time a member needs it; a failure only disables the fallback.
            nonlocal master, master_tried
            if not master_tried:
                master_tried = True
                try:
                    master = await self.upstox.exchange_instruments("NSE")
                except BrokerError as exc:
                    self._once("nse-master", logging.WARNING,
                               "scanner: the Upstox NSE master is unavailable, so index "
                               "members are not matched by ISIN (%s)", exc)
            return master

        lists = {uid: await self.universes.index_list(uid) for uid in index_ids}
        fno_names = (sorted(u for u in master.futures if ("NSE", u) in master.equities)
                     if "fno" in selected else [])

        # Data-path check (R3-F1): on a Dhan, synthetic or "other" path the first
        # min(3, N) lookups are made up front. If they all fail with the same message,
        # and it names none of their symbols, the path itself is failing: stop here
        # (no ISIN fallback for them, since such a target would use the same path).
        probed: dict[str, Instrument | BrokerError] = {}
        if not on_upstox:
            order: list[str] = []
            for uid in UNIVERSE_IDS:
                if uid in lists:
                    order += [m.symbol for m in lists[uid].members]
                elif uid == "fno" and uid in selected:
                    order += fno_names
            order += custom_nse
            first: list[str] = []
            for sym in order:
                if sym.upper() not in {s.upper() for s in first}:
                    first.append(sym)
                if len(first) == 3:
                    break
            for sym in first:
                try:
                    probed[sym.upper()] = await self.broker.resolve_equity(sym, "NSE")
                except BrokerError as exc:
                    probed[sym.upper()] = exc
            errors = [e for e in probed.values() if isinstance(e, BrokerError)]
            if first and len(errors) == len(first):
                msg = str(errors[0])
                if all(str(e) == msg for e in errors) and not any(s in msg for s in first):
                    log.error("scanner: the data path refuses every lookup: %s", msg)
                    raise BrokerError(msg, code=errors[0].code or "DATA_PATH",
                                      retryable=True) from errors[0]

        async def lookup(sym: str) -> Instrument:
            if on_upstox:
                return await self.upstox.lookup_equity(sym, "NSE")
            hit = probed.get(sym.upper())
            if isinstance(hit, BrokerError):
                raise hit
            if hit is not None:
                return hit
            return await self.broker.resolve_equity(sym, "NSE")

        async def resolve_nse(sym: str, origin: str, *, isin: str = "", name: str = "",
                              label: str = "") -> Target | None:
            try:
                inst = await lookup(sym)
                return self._target(inst, "NSE", name=name or None, origin=origin,
                                    tradable=True, chartable=True)
            except BrokerError as exc:
                reason = str(exc)
            # ISIN fallback for index members (renamed symbols, REITs).
            if isin and await isin_master() is not None:
                inst = master.by_key.get(f"NSE_EQ|{isin}")
                if inst is not None and (on_upstox or inst.symbol.upper() != sym.upper()):
                    ok = inst.instrument_type in EQUITY_TYPES
                    extra = []
                    if inst.symbol.upper() != sym.upper():
                        extra.append(f"listed as {sym} in {label}; scanned as {inst.symbol} "
                                     "(matched by ISIN)")
                    display = inst.display_name or name
                    if not on_upstox:
                        # F9: the master's current symbol, resolved through the data path.
                        try:
                            inst = await self.broker.resolve_equity(inst.symbol, "NSE")
                        except BrokerError as exc:
                            inst, reason = None, str(exc)
                    if inst is not None:
                        return self._target(inst, "NSE", name=display, origin=origin,
                                            tradable=ok, chartable=ok, notes=extra)
            skipped.append({"symbol": f"NSE:{sym}", "reason": reason, "origin": origin})
            log.debug("scanner: skipped NSE:%s (%s)", sym, reason)
            return None

        for uid in UNIVERSE_IDS:
            if uid not in selected:
                continue
            before = len(skipped)
            resolved: list[Target] = []
            if uid in INDEX_UNIVERSES:
                il = lists[uid]
                for m in il.members:
                    t = await resolve_nse(m.symbol, uid, isin=m.isin, name=m.name, label=il.label)
                    if t is not None:
                        resolved.append(t)
                for sym, reason in il.skipped:
                    skipped.append({"symbol": f"NSE:{sym}", "reason": reason, "origin": uid})
                info = {"id": uid, "label": il.label, "size": len(il.members),
                        "source": il.source, "as_of": il.as_of.isoformat()}
                if il.source in ("cache", "snapshot"):
                    notes.append(f"{il.label} list from the {il.source} of {il.as_of.isoformat()}: "
                                 "live fetch failed")
            elif uid == "fno":
                names = sorted(u for u in master.futures if ("NSE", u) in master.equities)
                for sym in names:
                    t = await resolve_nse(sym, uid)
                    if t is not None:
                        resolved.append(t)
                self.universes.note_derived(uid, len(names), self.day)
                info = {"id": uid, "label": DERIVED_UNIVERSES[uid][0], "size": len(names),
                        "source": DERIVED_SOURCE, "as_of": self.day.isoformat()}
            else:   # mcx
                try:
                    rows = await self.upstox.commodity_underlyings()
                except BrokerError as exc:
                    if not index_ids and "fno" not in selected and not spec.custom:
                        raise BrokerError(str(exc), code=exc.code or "MASTER",
                                          retryable=True) from exc
                    self._once("mcx-master", logging.WARNING,
                               "scanner: MCX commodities unavailable (%s)", exc)
                    notes.append(f"MCX commodities skipped: {exc}")
                    rows = []
                for inst in rows:
                    under = (inst.underlying or inst.symbol).upper()
                    resolved.append(self._target(inst, "MCX", name=inst.symbol, symbol=under,
                                                 origin=uid, tradable=False, chartable=True))
                self.universes.note_derived(uid, len(rows), self.day)
                info = {"id": uid, "label": DERIVED_UNIVERSES[uid][0], "size": len(rows),
                        "source": DERIVED_SOURCE, "as_of": self.day.isoformat()}
            info["resolved"] = len(resolved)
            info["skipped"] = len(skipped) - before
            universes.append(info)
            targets.extend(resolved)

        for exchange, sym in spec.custom:
            if exchange == "NSE":
                t = await resolve_nse(sym, "custom")
                if t is not None:
                    targets.append(t)
                continue
            try:
                if exchange == "BSE":
                    inst = await self.upstox.lookup_equity(sym, "BSE")
                    targets.append(self._target(inst, "BSE", origin="custom",
                                                tradable=True, chartable=True))
                else:
                    inst = await self.upstox.resolve_commodity(sym)
                    under = (inst.underlying or sym).upper()
                    targets.append(self._target(inst, "MCX", name=inst.symbol, symbol=under,
                                                origin="custom", tradable=False, chartable=True))
            except BrokerError as exc:
                if "instrument list" in str(exc):
                    self._once(f"master-{exchange}", logging.WARNING,
                               "scanner: the Upstox %s master is unavailable (%s)", exchange, exc)
                skipped.append({"symbol": f"{exchange}:{sym}", "reason": str(exc),
                                "origin": "custom"})

        merged: dict[str, Target] = {}
        for t in targets:
            seen = merged.get(t.key)
            if seen is None:
                merged[t.key] = t
                continue
            for o in t.origins:
                if o not in seen.origins:
                    seen.origins.append(o)
            for n in t.notes:
                if n not in seen.notes:
                    seen.notes.append(n)
        final = list(merged.values())
        if len(final) > MAX_TARGETS:
            raise ValueError(f"the selection has {len(final):,} symbols; the limit is 1,000")
        if skipped:
            notes.append(f"{len(skipped)} symbol(s) skipped")
        if not final and skipped:
            notes.append(f"nothing to scan: all {len(skipped)} symbols were skipped "
                         f"(first reason: {skipped[0]['reason']})")
            log.info("scanner: nothing to scan, %d symbols skipped", len(skipped))
        return Expansion(final, universes, notes, skipped)

    # ---- fetching ----
    async def _fetch(self, target: Target, n: int, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(3):
            self._check_pin()
            try:
                async with self.budget.spend(n, target.provider):
                    self._check_pin()           # the wait for tokens can be long
                    return await call()
            except BrokerError as exc:
                if exc.status == 429 or exc.code == "DH-904":
                    self.budget.penalise_429(target.provider)
                    self._once(f"429-{target.provider}", logging.WARNING,
                               "%s rate limit hit; slowing down", target.provider)
                if exc.code == "BUDGET":
                    self._once("budget", logging.WARNING, "scanner: %s", exc)
                if not exc.retryable or attempt == 2:
                    raise
            await asyncio.sleep((2.0, 5.0)[attempt])   # the retry takes fresh tokens
        raise AssertionError("unreachable")

    def today_needed(self, target: Target) -> bool:
        if self.day.weekday() >= 5:
            return False
        return self.clock() >= session_open(target.instrument.segment, self.day)

    def watch_today(self, targets: list[Target]) -> None:
        """F14: on a non-Upstox data path, watch the first min(3, N) NSE today fetches."""
        nse = [t for t in targets if t.exchange == "NSE"]
        if self.provider != "upstox" and nse:
            self.today_watch = _TodayWatch(min(3, len(nse)))

    async def _await_verdict(self, watch: _TodayWatch) -> None:
        while not watch.decided.is_set():
            if self.budget.cancelled():
                raise ScanCancelled()
            self._check_pin()
            try:
                await asyncio.wait_for(watch.decided.wait(), 0.5)
            except asyncio.TimeoutError:
                pass

    async def today(self, target: Target, interval: int) -> CandleSeries:
        if not self.today_needed(target):
            return CandleSeries([])
        watch = self.today_watch
        if watch is None or target.exchange != "NSE" or watch.decided.is_set():
            pass
        elif watch.started < watch.n:
            watch.started += 1
            try:
                series = await self._today(target, interval)
            except BrokerError as exc:
                watch.record(target.symbol, exc)
                if watch.stopped is not None:
                    self._once("today-stopped", logging.ERROR,
                               "scanner: the data path refuses today's candles: %s",
                               watch.stopped)
                raise
            except BaseException:
                watch.clear()
                raise
            watch.clear()
            return series
        else:
            await self._await_verdict(watch)
        if watch is not None and target.exchange == "NSE" and watch.stopped is not None:
            watch.dropped += 1
            raise DataPathStopped(watch.stopped)
        return await self._today(target, interval)

    async def _today(self, target: Target, interval: int) -> CandleSeries:
        node = self.broker_for(target)
        inst = target.instrument
        series = await self._fetch(
            target, 1, lambda: node.today_candles(inst, interval, day=self.day))
        return CandleSeries([c for c in series.candles if c.ts.date() == self.day])

    def history_key(self, target: Target, source: "Source") -> str:
        start, end = source.window(self.day)
        return f"{target.source}|{target.key}|{source.base}|{start}|{end}"

    async def history(self, target: Target, source: "Source") -> CandleSeries:
        start, end = source.window(self.day)
        node = self.broker_for(target)
        inst = target.instrument
        if target.provider == "synthetic":   # computed locally: never cached, never incomplete
            return await self._fetch(
                target, 1, lambda: node.history_window(inst, source.base, start, end))
        key = self.history_key(target, source)
        series = await self.cache.get(key)
        if series is None:
            n = len(request_pieces(source.base, start, end)) if target.provider == "upstox" else 1
            try:
                series = await self._fetch(
                    target, n, lambda: node.history_window(inst, source.base, start, end))
            except BrokerError as exc:
                if exc.code == "UDAPI1148":
                    self._once("udapi1148", logging.ERROR,
                               "Upstox refused a history window (Invalid date range) for %s %s "
                               "%s..%s: the request-piece rule needs updating",
                               target.symbol, source.name, start, end)
                raise
            await self.cache.put(key, series, end=end)
        last = series.last
        if last is None or last.ts.date() != end:
            self.incomplete.setdefault(target.key, (source.name, end))
            early = self.clock() < datetime.combine(self.day, HISTORY_PUBLISHED_BY, tzinfo=IST)
            if early:
                text = (f"no {_short_day(end)} session in its {source.name} history yet: Upstox "
                        "may not have published it when this was fetched (refetched after 30 "
                        "minutes, final from 09:00)")
            else:
                text = (f"no {_short_day(end)} session in its {source.name} history (an exchange "
                        "holiday, no trades that day, or published late)")
            if not any(n.startswith(f"no {_short_day(end)} session") for n in
                       self.symbol_notes.get(target.key, [])):
                self._symbol_note(target, text)
        return series

    def close_time(self, target: Target, history: dict[str, CandleSeries],
                   plan: "Plan") -> time | None:
        """None for NSE/BSE. For MCX the session end derived from the finest loaded
        intraday source whose base divides 30 minutes, capped at the DST rule."""
        if target.exchange != "MCX":
            return None
        fallback = mcx_close_time(self.day)
        usable = [s for s in plan.sources
                  if s.base < DAY and 30 % s.base == 0 and history.get(s.name)]
        if not usable:
            return fallback
        src = min(usable, key=lambda s: s.base)
        last_of: dict[date, Candle] = {}
        for c in history[src.name].candles:
            d = c.ts.date()
            if d < self.day:
                last_of[d] = c
        kept: list[time] = []
        for d in sorted(last_of)[-5:]:
            end = last_of[d].ts + timedelta(minutes=src.base)
            end = min(end, datetime.combine(d, time(23, 55), tzinfo=IST))
            minutes = end.hour * 60 + end.minute + (1 if end.second or end.microsecond else 0)
            minutes = -(-minutes // 5) * 5
            if end.date() != d or minutes > 23 * 60 + 55 or minutes < 12 * 60:
                continue
            kept.append(time(minutes // 60, minutes % 60))
        return min(max(kept), fallback) if kept else fallback
