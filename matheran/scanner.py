"""Live BUY/SELL scanner: condition rows, validation of the scanner settings.

Each row is an exit-rule row (rules.py) with its own timeframe `tf`, evaluated by
default on the forming candle of that timeframe with its close at the live price
(`'on': live`, TradingView's real-time behaviour) or on the last closed candle
(`'on': close`). Rows are joined by AND / OR, AND binding tighter. The SELL rows are
the mirror of the BUY rows unless they are saved separately ("unlinked").

The scanner is read-only: it never places orders or creates watches.
"""

from __future__ import annotations

import asyncio
import logging
import math
import secrets
import time as _time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time
from functools import reduce
from pathlib import Path
from typing import Callable

from . import rules
from . import timeframes as tf_table
from .brokers import Broker, BrokerError, DhanBroker, UpstoxData, data_node, find_upstox
from .brokers.upstox import REQUEST_TAG, UPSTOX_REQUESTS, request_pieces
from .candles import DAY, MONTH, WEEK, CandleSeries, drop_forming, resample
from .scan_data import (  # noqa: F401  (ScanBusy and the data types are re-exported)
    WINDOW,
    Budget,
    BrokerSwapped,
    DataPathStopped,
    Expansion,
    HistoryCache,
    LedgerFile,
    QuoteBook,
    RunLock,
    ScanBusy,
    ScanCancelled,
    ScanFeed,
    Target,
    available_now,
    busy_text,
    data_source_name,
    eta_seconds,
)
from .timeutil import IST, mcx_close_time, now_ist, previous_trading_day, session_open
from .universes import (
    INDEX_UNIVERSES,
    MAX_CUSTOM,
    UNIVERSE_IDS,
    UniverseStore,
    UniverseUnavailable,
    parse_symbol,
)

log = logging.getLogger(__name__)

SCAN_MIN_BARS = 200
WARMUP_FACTOR = 5
MAX_SYMBOLS = 1000
AUTO_COMPLETE_MAX_REQUESTS = 600     # "auto" runs complete only up to this estimate (≈100 s at 6/s)
SESSION_LOCAL_OPERANDS = {"vwap", "close", "open", "high", "low", "value"}
ON_LABELS = {"live": "live (forming candle)", "close": "last closed candle"}

SIDES = ("both", "buy", "sell")
EVALUATIONS = ("auto", "complete", "lazy")
AUTO_RESCAN_MINUTES = (0, 2, 5, 10, 15, 30, 60)
MAX_UNIVERSES = 10

_ST = {"ind": "supertrend", "period": 21, "factor": 0.618}
# FR-1, the same rows as config.example.yaml.
_DEFAULT_BUY_RAW = [
    {"tf": "1W", "left": {"ind": "rsi", "period": 14}, "op": "at_or_above",
     "right": {"ind": "value", "value": 50}, "on": "live"},
    {"tf": "1D", "join": "AND", "left": {"ind": "close"}, "op": "at_or_above",
     "right": {"ind": "ema", "period": 200}, "on": "live"},
    {"tf": "1D", "join": "AND", "left": {"ind": "close"}, "op": "above", "right": dict(_ST), "on": "live"},
    {"tf": "2h", "join": "AND", "left": {"ind": "close"}, "op": "above", "right": dict(_ST), "on": "live"},
    {"tf": "5m", "join": "AND", "left": {"ind": "close"}, "op": "above", "right": dict(_ST), "on": "live"},
    {"tf": "15m", "join": "AND", "left": {"ind": "close"}, "op": "above", "right": {"ind": "vwap"},
     "on": "live"},
    {"tf": "15m", "join": "AND", "left": {"ind": "rsi", "period": 21}, "op": "at_or_above",
     "right": {"ind": "rsi_ema", "rsi": 21, "period": 14}, "on": "live"},
]


def normalize_side_rows(raw, side: str) -> list[dict]:
    """Validate one side's rows: 1-12 rows, each with a timeframe; 'on' defaults to live."""
    return rules.normalize_rows(raw, label=f"{side} condition", setting=f"scanner.{side.lower()}_rules",
                                min_rows=1, timeframes=True, default_on="live")


DEFAULT_BUY_ROWS: list[dict] = normalize_side_rows(_DEFAULT_BUY_RAW, "BUY")


def effective_rows(saved, buy_raw=None, sell_raw=None,
                   sell_linked: bool | None = None) -> tuple[list[dict], list[dict], bool]:
    """(buy, sell, linked). The one meaning of null on every endpoint: null rows are the
    saved rows, or the defaults when none are saved; a null sell_linked is "linked iff
    no SELL rows are saved". `saved` is cfg.scanner, already normalised."""
    buy = normalize_side_rows(buy_raw, "BUY") if buy_raw is not None else (
        saved.buy_rules or DEFAULT_BUY_ROWS)
    linked = (saved.sell_rules is None) if sell_linked is None else bool(sell_linked)
    if linked:
        return buy, rules.mirror_rules(buy), True
    if sell_raw is not None:
        return buy, normalize_side_rows(sell_raw, "SELL"), False
    return buy, (saved.sell_rules if saved.sell_rules is not None else rules.mirror_rules(buy)), False


# --------------------------------------------------------------- settings
def _number(value, name: str) -> float:
    """A finite number from YAML/JSON. Booleans are rejected (True is an int)."""
    if isinstance(value, bool):
        raise ValueError(f"scanner.{name} must be a number, got {value!r}")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise ValueError(f"scanner.{name} must be a number, got {value!r}") from None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"scanner.{name} must be a finite number, got {value!r}")
    return float(value)


def _int_in(value, name: str, lo: int, hi: int) -> int:
    num = _number(value, name)
    if not num.is_integer() or not lo <= num <= hi:
        raise ValueError(f"scanner.{name} must be a whole number from {lo:,} to {hi:,}, got {value!r}")
    return int(num)


def _choice(value, name: str, choices: tuple[str, ...]) -> str:
    text = value.strip().lower() if isinstance(value, str) else None
    if text not in choices:
        listed = ", ".join(choices[:-1]) + " or " + choices[-1]
        raise ValueError(f"scanner.{name} must be {listed}, got {value!r}")
    return text


def validate_config(sc) -> None:
    """Validate and normalise cfg.scanner in place (called from config.validate).
    Types are checked before any string method runs, so a wrong type is a ValueError
    (400 and rollback), never an AttributeError."""
    sc.buy_rules = None if sc.buy_rules is None else normalize_side_rows(sc.buy_rules, "BUY")
    sc.sell_rules = None if sc.sell_rules is None else normalize_side_rows(sc.sell_rules, "SELL")

    if not isinstance(sc.universes, (list, tuple)):
        raise ValueError("scanner.universes must be a list")
    universes: list[str] = []
    for item in sc.universes:
        if not isinstance(item, str):
            raise ValueError(f"scanner.universes: universe ids are strings, got {item!r}")
        uid = item.strip().lower()
        if uid not in UNIVERSE_IDS:
            raise ValueError(
                f"scanner.universes: unknown universe {item.strip()!r}. Available: {', '.join(UNIVERSE_IDS)}"
            )
        if uid not in universes:
            universes.append(uid)
    if len(universes) > MAX_UNIVERSES:
        raise ValueError(f"scanner.universes: at most {MAX_UNIVERSES}, got {len(universes)}")
    sc.universes = universes

    if not isinstance(sc.custom_symbols, (list, tuple)):
        raise ValueError("scanner.custom_symbols must be a list")
    if len(sc.custom_symbols) > MAX_CUSTOM:
        raise ValueError(
            f"scanner.custom_symbols: at most {MAX_CUSTOM} symbols, got {len(sc.custom_symbols)}"
        )
    symbols: list[str] = []
    for item in sc.custom_symbols:
        exchange, symbol = parse_symbol(item)
        key = f"{exchange}:{symbol}"
        if key not in symbols:
            symbols.append(key)
    sc.custom_symbols = symbols

    sc.side = _choice(sc.side, "side", SIDES)
    sc.evaluation = _choice(sc.evaluation, "evaluation", EVALUATIONS)
    minutes = _number(sc.auto_rescan_minutes, "auto_rescan_minutes")
    if minutes not in AUTO_RESCAN_MINUTES:
        raise ValueError(
            "scanner.auto_rescan_minutes must be one of "
            f"{', '.join(map(str, AUTO_RESCAN_MINUTES))}, got {sc.auto_rescan_minutes!r}"
        )
    sc.auto_rescan_minutes = int(minutes)
    sc.max_requests_per_30min = _int_in(sc.max_requests_per_30min, "max_requests_per_30min", 100, 1850)
    rate = _number(sc.requests_per_second, "requests_per_second")
    if not 0.5 <= rate <= 8:
        raise ValueError(
            f"scanner.requests_per_second must be between 0.5 and 8, got {sc.requests_per_second!r}"
        )
    sc.requests_per_second = rate
    sc.concurrency = _int_in(sc.concurrency, "concurrency", 1, 16)


# ---------------------------------------------------------------- wording
def catalog() -> dict:
    """Everything the Scanner tab's row builder needs."""
    return {
        **rules.catalog(),
        "on": [{"id": k, "label": v} for k, v in ON_LABELS.items()],
        "timeframes": tf_table.info(),
    }


_SYMBOLS = {"above": ">", "below": "<", "at_or_above": "≥", "at_or_below": "≤",
            "crosses_above": "×↑", "crosses_below": "×↓"}


def operand_word(o: dict, live: bool) -> str:
    """An operand in the scanner's short wording: Price (live) or Close, ST(21, 0.618)."""
    ind = o["ind"]
    if ind == "close":
        return "Price" if live else "Close"
    if ind == "supertrend":
        return f"ST({o['period']}, {float(o['factor']):g})"
    return rules.describe_operand(o)


def short_label(row: dict) -> str:
    """ "1W RSI(14) ≥ 50", "1D Price > ST(21, 0.618)": a column header."""
    live = row.get("on") == "live"
    return (f"{row['tf']} {operand_word(row['left'], live)} {_SYMBOLS[row['op']]} "
            f"{operand_word(row['right'], live)}")


# ------------------------------------------------------------------- spec
class ScanIdle(Exception):
    """Cancel with nothing running (API 409)."""


class ScanRefused(Exception):
    """An auto-rescan that does not fit the budget (API 429)."""


TRIGGERS = ("manual", "auto")
AUTO_INTERVALS = (2, 5, 10, 15, 30, 60)


def _body_choice(value, name: str, choices: tuple[str, ...]) -> str:
    text = value.strip().lower() if isinstance(value, str) else None
    if text not in choices:
        listed = ", ".join(choices[:-1]) + " or " + choices[-1]
        raise ValueError(f"{name} must be {listed}, got {value!r}")
    return text


@dataclass(frozen=True, slots=True)
class ScanSpec:
    """The validated request for one run."""
    buy: list
    sell: list
    sell_linked: bool
    universes: tuple[str, ...]
    custom: tuple[tuple[str, str], ...]
    side: str
    evaluation: str
    trigger: str = "manual"
    interval_minutes: int | None = None   # auto-rescan interval; required when trigger == "auto"

    @classmethod
    def build(cls, saved, body: dict | None = None) -> "ScanSpec":
        """Body fields override the saved ones (cfg.scanner). ValueError names the field."""
        body = dict(body or {})
        buy, sell, linked = effective_rows(saved, body.get("buy_rules"), body.get("sell_rules"),
                                           body.get("sell_linked"))
        raw = body.get("universes")
        raw = saved.universes if raw is None else raw
        if not isinstance(raw, (list, tuple)):
            raise ValueError("universes must be a list of universe ids")
        universes: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                raise ValueError(f"universes: universe ids are strings, got {item!r}")
            uid = item.strip().lower()
            if uid not in UNIVERSE_IDS:
                raise ValueError(f"universes: unknown universe {item.strip()!r}. "
                                 f"Available: {', '.join(UNIVERSE_IDS)}")
            if uid not in universes:
                universes.append(uid)
        if len(universes) > MAX_UNIVERSES:
            raise ValueError(f"universes: at most {MAX_UNIVERSES}, got {len(universes)}")
        raw = body.get("custom_symbols")
        raw = saved.custom_symbols if raw is None else raw
        if not isinstance(raw, (list, tuple)):
            raise ValueError("custom_symbols must be a list such as [\"NSE:RELIANCE\"]")
        if len(raw) > MAX_CUSTOM:
            raise ValueError(f"custom_symbols: at most {MAX_CUSTOM} symbols, got {len(raw)}")
        custom: list[tuple[str, str]] = []
        for item in raw:
            try:
                pair = parse_symbol(item)
            except ValueError as exc:
                raise ValueError(f"custom_symbols: {exc}") from None
            if pair not in custom:
                custom.append(pair)
        if not universes and not custom:
            raise ValueError("select at least one universe or custom symbol")
        side = body.get("side")
        side = _body_choice(saved.side if side is None else side, "side", SIDES)
        evaluation = body.get("evaluation")
        evaluation = _body_choice(saved.evaluation if evaluation is None else evaluation,
                                  "evaluation", EVALUATIONS)
        trigger = _body_choice(body.get("trigger") or "manual", "trigger", TRIGGERS)
        interval = body.get("interval_minutes")
        if trigger == "auto":
            if isinstance(interval, bool) or interval not in AUTO_INTERVALS:
                raise ValueError("interval_minutes must be one of "
                                 f"{', '.join(map(str, AUTO_INTERVALS))} for an auto run, "
                                 f"got {interval!r}")
            interval = int(interval)
        else:
            interval = None
        return cls(buy=buy, sell=sell, sell_linked=linked, universes=tuple(universes),
                   custom=tuple(custom), side=side, evaluation=evaluation, trigger=trigger,
                   interval_minutes=interval)

    def sides(self) -> tuple[str, ...]:
        return {"both": ("BUY", "SELL"), "buy": ("BUY",), "sell": ("SELL",)}[self.side]

    def rows_by_side(self) -> dict[str, list[dict]]:
        return {s: (self.buy if s == "BUY" else self.sell) for s in self.sides()}


# ------------------------------------------------------------------- plan
PLAN_SEGMENTS = {"NSE": "NSE_EQ", "MCX": "MCX_COMM"}   # segment classes: NSE/BSE and MCX


def segment_class(target: Target) -> str:
    return "MCX" if target.exchange == "MCX" else "NSE"


def _pieces(base: int, sessions: int, today: date) -> int:
    return len(request_pieces(base, previous_trading_day(today, sessions),
                              previous_trading_day(today, 1)))


@dataclass(slots=True)
class Source:
    name: str
    base: int
    sessions: int
    serves: set[int]

    def window(self, today: date) -> tuple[date, date]:
        return previous_trading_day(today, self.sessions), previous_trading_day(today, 1)

    def pieces(self, today: date) -> int:
        return len(request_pieces(self.base, *self.window(today)))


@dataclass(slots=True)
class RowRef:
    side: str
    index: int
    row: dict
    minutes: int
    source: str
    session_local: bool
    bars: int


@dataclass(slots=True)
class Plan:
    segment: str
    today_interval: int
    sources: list[Source]
    refs: dict[str, list[RowRef]]

    def source_for(self, minutes: int) -> str | None:
        for s in self.sources:
            if minutes in s.serves:
                return s.name
        return None

    def as_dict(self, today: date) -> dict:
        return {"segment": self.segment, "today_interval": self.today_interval,
                "sources": [{"name": s.name, "base": s.base, "sessions": s.sessions,
                             "window": [d.isoformat() for d in s.window(today)],
                             "requests": s.pieces(today)} for s in self.sources]}


def build_plan(rows_by_side: dict[str, list[dict]], segment: str, today: date) -> Plan:
    """History sources and today's interval for one segment class (design §6.7)."""
    need: dict[int, int] = {}
    meta: list[tuple[str, int, dict, int, int]] = []
    for side, rows in rows_by_side.items():
        for i, row in enumerate(rows):
            m = tf_table.CODE_MINUTES[row["tf"]]
            bars = max(SCAN_MIN_BARS, WARMUP_FACTOR * rules.row_warmup(row))
            need[m] = max(need.get(m, 0), tf_table.sessions_for(m, bars, segment))
            meta.append((side, i, row, m, bars))
    intraday = sorted(m for m in need if m < DAY)
    today_interval = reduce(math.gcd, intraday) if intraday else DAY
    sources: list[Source] = []
    serving: dict[int, str] = {}
    daily = sorted(m for m in need if m >= DAY)
    if daily:
        sources.append(Source("day", DAY, max(need[m] for m in daily), set(daily)))
        serving.update({m: "day" for m in daily})
    intra: list[Source] = []
    for m in intraday:
        for s in intra:
            if (m % s.base == 0 and _pieces(s.base, max(s.sessions, need[m]), today)
                    == _pieces(s.base, s.sessions, today)):
                s.sessions = max(s.sessions, need[m])
                s.serves.add(m)
                serving[m] = s.name
                break
        else:
            s = Source(f"m{m}", m, need[m], {m})
            intra.append(s)
            serving[m] = s.name
    intra.sort(key=lambda s: (s.pieces(today), s.sessions, s.base))
    sources += intra
    refs: dict[str, list[RowRef]] = {side: [] for side in rows_by_side}
    for side, i, row, m, bars in meta:
        local = (m < DAY and row["left"]["ind"] in SESSION_LOCAL_OPERANDS
                 and row["right"]["ind"] in SESSION_LOCAL_OPERANDS
                 and not row["op"].startswith("crosses"))
        refs[side].append(RowRef(side, i, row, m, serving[m], local, bars))
    return Plan(segment, today_interval, sources, refs)


# ------------------------------------------------------------- evaluation
@dataclass(slots=True)
class SymbolData:
    target: Target
    plan: Plan
    now: datetime
    today: CandleSeries
    history: dict[str, CandleSeries]
    ltp: float | None
    close_time: time | None
    calcs: dict[tuple[int, str, str], rules.SeriesCalc] = field(default_factory=dict)
    ltp_at: datetime | None = None          # when the quote in ltp was fetched
    kept: dict[tuple[int, str, str], CandleSeries] = field(default_factory=dict)


@dataclass(slots=True)
class RowEval:
    result: rules.RowResult
    bars: int
    short_history: bool


def series_for(data: SymbolData, minutes: int, scope: str) -> CandleSeries:
    seg = data.target.instrument.segment
    if scope == "today":
        return resample(data.today, minutes, seg)
    if minutes < DAY:
        hist = data.history.get(data.plan.source_for(minutes) or "", CandleSeries([]))
        return tf_table.merge_series(resample(hist, minutes, seg), resample(data.today, minutes, seg))
    daily = tf_table.merge_series(data.history.get("day", CandleSeries([])),
                                  resample(data.today, DAY, seg))
    return daily if minutes == DAY else resample(daily, minutes, seg)


def calc_for(data: SymbolData, minutes: int, on: str, scope: str) -> rules.SeriesCalc:
    key = (minutes, on, scope)
    calc = data.calcs.get(key)
    if calc is None:
        series = series_for(data, minutes, scope)
        closed, forming = drop_forming(series, minutes, data.now, data.target.instrument.segment,
                                       close_time=data.close_time)
        calc = rules.SeriesCalc(closed if on == "close" else
                                rules.live_series(closed, forming, data.ltp))
        data.calcs[key] = calc
    return calc


def evaluate_refs(data: SymbolData, refs: list[RowRef], scope: str) -> dict[tuple[str, int], RowEval | None]:
    """Pure and synchronous (run in a thread). None for a session-local ref whose bar is
    not in today's candles yet: it is deferred to its source's stage."""
    out: dict[tuple[str, int], RowEval | None] = {}
    for ref in refs:
        on = ref.row["on"]
        calc = calc_for(data, ref.minutes, on, scope)
        if scope == "today" and calc.n == 0:
            out[(ref.side, ref.index)] = None
            continue
        rr = rules.evaluate_row(ref.index, ref.row, calc, rules.describe_rule(ref.row))
        defined = rr.state in ("true", "false")
        out[(ref.side, ref.index)] = RowEval(rr, calc.n, scope == "full" and defined
                                             and calc.n < ref.bars)
        data.kept[(ref.minutes, on, scope)] = calc.series
    return out


def price_summary(data: SymbolData) -> tuple[float | None, date | None, float | None, datetime | None]:
    """(ltp, price_day, prev_close, as_of): the quote if one was used, else the last close
    of today's bars, else the newest history bar; prev_close is the last daily close before
    price_day, else the last intraday close before it."""
    if data.ltp is not None:
        ltp = data.ltp
        as_of = data.ltp_at or data.now
        price_day = data.today.candles[-1].ts.date() if data.today else as_of.date()
    elif data.today:
        last = data.today.candles[-1]
        ltp, price_day, as_of = last.close, last.ts.date(), last.ts
    else:
        newest = None
        for s in data.history.values():
            if s and (newest is None or s.candles[-1].ts > newest.ts):
                newest = s.candles[-1]
        if newest is None:
            return None, None, None, None
        ltp, price_day, as_of = newest.close, newest.ts.date(), newest.ts
    prev = None
    day = data.history.get("day")
    if day:
        for c in reversed(day.candles):
            if c.ts.date() < price_day:
                prev = c.close
                break
    if prev is None:
        best = None
        for name, s in data.history.items():
            if name == "day":
                continue
            for c in reversed(s.candles):
                if c.ts.date() < price_day:
                    if best is None or c.ts > best.ts:
                        best = c
                    break
        prev = best.close if best is not None else None
    return ltp, price_day, prev, as_of


def session_open_now(target: Target, close_time: time | None, now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    start = session_open(target.instrument.segment, now.date())
    if target.exchange == "MCX":
        end_t = close_time or mcx_close_time(now.date())
    else:
        end_t = time(15, 30)
    return start <= now < datetime.combine(now.date(), end_t, tzinfo=IST)


SKIPPED_TEXT = "not checked: another condition already failed (lazy mode)"


def _bar_text(tf: str, minutes: int, ts: datetime | None, scan_day: date) -> str:
    if ts is None:
        return f"{tf} bar"
    d = f"{ts.day} {ts:%b}"
    if minutes >= MONTH:
        return f"{tf} bar of {ts:%b %Y}"
    if minutes >= WEEK:
        return f"{tf} bar from {d}"
    if minutes >= DAY:
        return f"{tf} bar of {d}"
    if ts.date() != scan_day:
        return f"{tf} bar of {d} {ts:%H:%M}"
    return f"{tf} bar of {ts:%H:%M}"


def cell_detail(ref: RowRef, rr: rules.RowResult, data: SymbolData) -> str:
    """A cell's tooltip in short_label wording, e.g.
    "Price 1174.60 ≥ EMA(200) 1100.00 · 1D bar of 15 Oct (live)"."""
    if rr.state == "skipped":
        return SKIPPED_TEXT
    if rr.state not in ("true", "false") or rr.left is None or rr.right is None:
        return rr.detail
    row = ref.row
    live = row["on"] == "live"
    left = operand_word(row["left"], live)
    right = operand_word(row["right"], live)
    if row["right"]["ind"] != "value":
        right = f"{right} {rr.right:.2f}"
    bar = _bar_text(row["tf"], ref.minutes, rr.candle_ts, data.now.date())
    return (f"{left} {rr.left:.2f} {_SYMBOLS[row['op']]} {right} · {bar} "
            f"({'live' if live else 'last closed'})")


# ---------------------------------------------------------------- results
def _r4(v):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), 4)


@dataclass(slots=True)
class RowCell:
    state: str                      # "true" | "false" | "unavailable" | "skipped"
    left: float | None
    right: float | None
    candle_ts: datetime | None
    bars: int
    short_history: bool
    detail: str

    def as_dict(self) -> dict:
        return {"state": self.state, "left": _r4(self.left), "right": _r4(self.right),
                "candle_ts": self.candle_ts.isoformat() if self.candle_ts else None,
                "bars": self.bars, "short_history": self.short_history, "detail": self.detail}


@dataclass(slots=True)
class SideResult:
    signal: bool
    met: int
    checked: int
    total: int
    na: int
    rows: list[RowCell]

    def as_dict(self) -> dict:
        return {"signal": self.signal, "met": self.met, "checked": self.checked,
                "total": self.total, "na": self.na, "rows": [c.as_dict() for c in self.rows]}


@dataclass(slots=True)
class SymbolResult:
    seq: int
    target: Target
    status: str                     # "ok" | "error" | "no_data"
    error: str
    data_error: bool
    synthetic: bool
    ltp: float | None
    prev_close: float | None
    change_pct: float | None
    price_day: date | None
    as_of: datetime | None
    notes: list[str]
    sides: dict[str, SideResult]
    series: dict | None = None      # keep_series only: {(minutes, on, scope): CandleSeries}

    def as_dict(self) -> dict:
        t = self.target
        return {"seq": self.seq, "exchange": t.exchange, "symbol": t.symbol, "name": t.name,
                "chart": t.chart_symbol, "tradable": t.tradable, "chartable": t.chartable,
                "origins": list(t.origins), "status": self.status, "error": self.error,
                "data_error": self.data_error, "synthetic": self.synthetic,
                "ltp": _r4(self.ltp), "prev_close": _r4(self.prev_close),
                "change_pct": _r4(self.change_pct),
                "price_day": self.price_day.isoformat() if self.price_day else None,
                "as_of": self.as_of.isoformat() if self.as_of else None,
                "notes": list(self.notes),
                "sides": {s: r.as_dict() for s, r in self.sides.items()}}


# --------------------------------------------------------------- estimate
def build_plans(spec: ScanSpec, targets: list[Target], today: date) -> dict[str, Plan]:
    """One plan per segment class present (NSE is always built, for the columns)."""
    classes = {"NSE"} | {segment_class(t) for t in targets}
    rows = spec.rows_by_side()
    return {cls: build_plan(rows, PLAN_SEGMENTS[cls], today) for cls in sorted(classes)}


async def compute_estimate(feed: ScanFeed, expansion: Expansion, plans: dict[str, Plan],
                           spec: ScanSpec, options, *, available: int,
                           quote_batches: int) -> dict:
    """Requests a run of `spec` would make (design §6.7 "estimate"). The cache is
    checked with one exists_many call in a worker thread."""
    targets = expansion.targets
    keys = [feed.history_key(t, s) for t in targets if t.provider != "synthetic"
            for s in plans[segment_class(t)].sources]
    cached = await asyncio.to_thread(feed.cache.exists_many, keys) if keys else set()
    complete = lazy = minimum = repeat = cached_symbols = 0
    by_provider: dict[str, int] = {}
    lazy_by: dict[str, int] = {}
    for t in targets:
        if t.provider == "synthetic":
            continue
        plan = plans[segment_class(t)]
        today = 1 if feed.today_needed(t) else 0
        costs = [0 if feed.history_key(t, s) in cached else
                 (s.pieces(feed.day) if t.provider == "upstox" else 1) for s in plan.sources]
        if plan.sources and not any(costs):
            cached_symbols += 1
        full, first = today + sum(costs), today + (costs[0] if costs else 0)
        complete += full
        lazy += first
        minimum += today
        repeat += today
        by_provider[t.provider] = by_provider.get(t.provider, 0) + full
        lazy_by[t.provider] = lazy_by.get(t.provider, 0) + first
    auto_eval = "complete" if complete <= min(available, AUTO_COMPLETE_MAX_REQUESTS) else "lazy"
    used = auto_eval if spec.evaluation == "auto" else spec.evaluation
    rate = float(options.requests_per_second)
    cap = int(options.max_requests_per_30min)
    now = _time.time()
    ages = [now - e for e in UPSTOX_REQUESTS.epochs(WINDOW, "scanner", external=True)]

    def eta(per_provider: dict[str, int]) -> int:
        out = 0.0
        for provider, n in per_provider.items():
            if provider == "upstox":
                out = max(out, eta_seconds(n, rate=rate, cap=cap, ages=ages))
            else:
                out = max(out, n / min(rate, 2.0))
        return int(round(out))

    warnings: list[str] = []
    source = feed.source_name
    if feed.provider == "dhan":
        warnings.append("NSE data via Dhan, paced at 2/s; the Upstox budget covers BSE and MCX only")
    elif feed.provider == "other":
        warnings.append(f"NSE data via {source}, paced at 2/s, without live quotes (prices are "
                        "candle closes); the Upstox budget covers BSE and MCX only")
    elif feed.synthetic:
        warnings.append("NSE data is synthetic (no data provider configured): the results are "
                        "not real market data")
    if lazy > available:
        warnings.append(f"needs about {lazy:,} requests; {available:,} are available now, so the "
                        "scan will pause until the budget frees up")
    if not targets and expansion.skipped:
        warnings.append(f"nothing to scan: all {len(expansion.skipped)} symbols were skipped "
                        f"(first reason: {expansion.skipped[0]['reason']})")
    return {
        "symbols": len(targets),
        "universes": expansion.universes,
        "skipped": expansion.skipped,
        "requests": {"complete": complete, "lazy_typical": lazy, "minimum": minimum,
                     "repeat": repeat, "quotes_per_30s": quote_batches,
                     "cached_symbols": cached_symbols, "by_provider": by_provider},
        "available": available,
        "evaluation_if_auto": auto_eval,
        "evaluation": used,
        "rate_per_second": rate,
        "eta_seconds": {"min": eta(by_provider if used == "complete" else lazy_by),
                        "max": eta(by_provider)},
        "data_source": source,
        "warnings": warnings,
    }


def _columns(rows: list[dict]) -> list[dict]:
    return [{"index": i, "tf": r["tf"], "on": r["on"], "text": rules.describe_rule(r),
             "label": short_label(r)} for i, r in enumerate(rows)]


def preview(saved, body: dict | None, today: date) -> dict:
    """The rows read back in words, their columns and the data plan per segment class
    (POST /api/scanner/preview). Rows resolve through effective_rows, as everywhere."""
    body = dict(body or {})
    buy, sell, linked = effective_rows(saved, body.get("buy_rules"), body.get("sell_rules"),
                                       body.get("sell_linked"))
    rows = {"BUY": buy, "SELL": sell}
    plans = {cls: build_plan(rows, seg, today) for cls, seg in PLAN_SEGMENTS.items()}
    nse = plans["NSE"]
    return {
        "buy": {"rules": buy, "text": rules.describe_rules(buy), "columns": _columns(buy)},
        "sell": {"rules": sell, "text": rules.describe_rules(sell), "columns": _columns(sell),
                 "linked": linked},
        "plan": {cls: p.as_dict(today) for cls, p in plans.items()},
        "per_symbol": {"first_scan_of_day": 1 + sum(s.pieces(today) for s in nse.sources),
                       "repeat": 1},
    }


# -------------------------------------------------------------------- job
ACTIVE_STATES = ("loading", "running", "waiting", "cancelling")
FINAL_STATES = ("done", "cancelled", "stopped", "failed")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _hms(dt: datetime | None) -> str:
    return dt.strftime("%H:%M:%S") if dt else "?"


class ScanJob:
    """One scan run: expansion, plan, estimate, then `concurrency` workers. Built by
    ScanManager.start after the run lock is held. No I/O in the constructor."""

    def __init__(self, spec: ScanSpec, *, options, feed: ScanFeed, budget: Budget,
                 quotes: QuoteBook, lock: RunLock, ledger_file: LedgerFile,
                 pinned_broker: Broker, engine=None, keep_series: bool = False,
                 job_id: str | None = None, clock: Callable[[], datetime] = now_ist) -> None:
        self.spec = spec
        self.options = options
        self.feed = feed
        self.budget = budget
        self.quotes = quotes
        self.lock = lock
        self.ledger_file = ledger_file
        self.pinned_broker = pinned_broker
        self.engine = engine
        self.keep_series = keep_series
        self.clock = clock
        self.id = job_id or secrets.token_hex(6)
        self.tag = f"scanner:{self.id}"
        self.trigger = spec.trigger
        self.state = "loading"
        self.started_at = clock()
        self.finished_at: datetime | None = None
        self.side = spec.side
        self.evaluation = spec.evaluation
        self.evaluation_used = spec.evaluation if spec.evaluation != "auto" else None
        self.evaluation_reason = "requested" if spec.evaluation != "auto" else ""
        self.universes: list[dict] = []
        self.skipped: list[dict] = []
        self.custom = len(spec.custom)
        self.total = 0
        self.scanned = 0
        self.matches = {s: 0 for s in spec.sides()}
        self.errors = 0
        self.na_symbols = 0
        self.skipped_rows = 0
        self.source_name = data_source_name(pinned_broker)
        self.estimate: dict | None = None
        self.checked_estimate: dict | None = None   # an auto run's estimate, from start()
        self.eta_seconds: float | None = None
        self.waiting_until: float | None = None
        self.notes: list[str] = []
        self.message = ""
        self.results: list[SymbolResult] = []
        self.rows = spec.rows_by_side()
        self.plans: dict[str, Plan] = {}
        self.task: asyncio.Task | None = None
        self._seq = 0                                 # seq starts at 1 in each job (F11)
        self._cancel = asyncio.Event()
        self._swapped = False
        self._queue: deque[Target] = deque()
        self._workers: list[asyncio.Task] = []
        self._done_times: deque[float] = deque(maxlen=21)
        self._warned: set[str] = set()
        self._hb_io: asyncio.Future | None = None     # the heartbeat's file I/O in flight

    # ---- callbacks ----
    def add_note(self, text: str) -> None:
        if text and text not in self.notes:
            self.notes.append(text)

    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def on_wait(self, until: float | None) -> None:
        if self.state not in ("running", "waiting"):
            return
        if until is None:
            self.state = "running"
            self.waiting_until = None
            return
        if self.state != "waiting":
            log.info("scanner: waiting for the request budget")
        self.state = "waiting"
        self.waiting_until = until

    def cancel(self) -> None:
        if self.state not in ACTIVE_STATES or self._cancel.is_set():
            return
        self._cancel.set()
        self.state = "cancelling"
        asyncio.get_running_loop().call_later(2.0, self._kill_workers)

    def _kill_workers(self) -> None:
        for w in self._workers:
            if not w.done():
                w.cancel()

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def requests(self) -> dict:
        out = {"upstox": UPSTOX_REQUESTS.total(self.tag), "quotes": self.quotes.requests,
               "dhan": self.budget.granted["dhan"]}
        if self.budget.granted["other"]:
            out["other"] = self.budget.granted["other"]
        return out

    # ---- run ----
    async def run(self) -> None:
        tag_token = REQUEST_TAG.set(self.tag)
        heartbeat: asyncio.Task | None = None
        try:
            UPSTOX_REQUESTS.set_external(await asyncio.to_thread(self.ledger_file.read_external))
            heartbeat = asyncio.create_task(self._heartbeat(), name="matheran-scan-heartbeat")
            await self.feed.cache.prune()
            expansion = await self.feed.expand(self.spec)
            self.universes = expansion.universes
            self.skipped = expansion.skipped
            for n in expansion.notes:
                self.add_note(n)
            targets = expansion.targets
            self.total = len(targets)
            self.plans = build_plans(self.spec, targets, self.feed.day)
            self.quotes.plan(targets)
            self.feed.watch_today(targets)
            self.estimate = await compute_estimate(
                self.feed, expansion, self.plans, self.spec, self.options,
                available=self.budget.available(), quote_batches=self.quotes.batches())
            if self.spec.evaluation == "auto":
                req = self.estimate["requests"]["complete"]
                limit = min(self.estimate["available"], AUTO_COMPLETE_MAX_REQUESTS)
                if req <= limit:
                    self.evaluation_used = "complete"
                    self.evaluation_reason = (f"complete: every condition needs ≈{req:,} "
                                              f"requests (auto runs complete up to {limit:,})")
                else:
                    self.evaluation_used = "lazy"
                    self.evaluation_reason = (f"lazy: every condition would need ≈{req:,} "
                                              f"requests (auto runs complete up to {limit:,})")
            if self._cancel.is_set():
                self.state = "cancelled"
                return
            self.state = "running"
            self._queue = deque(targets)
            n = min(int(self.options.concurrency), len(targets))
            self._workers = [asyncio.create_task(self._worker(), name=f"matheran-scan-{i}")
                             for i in range(n)]
            if self._workers:
                await asyncio.gather(*self._workers, return_exceptions=True)
            if self._swapped:
                self.state = "stopped"
                self.message = "the broker was changed during the scan; partial results kept"
                log.info("scanner: %s", self.message)
                if self.engine is not None and self.pinned_broker is not self.engine.broker:
                    try:
                        await self.pinned_broker.shutdown()
                    except Exception:  # noqa: BLE001
                        log.debug("scanner: closing the old broker failed", exc_info=True)
            elif self._cancel.is_set():
                self.state = "cancelled"
            else:
                self.state = "done"
                watch = self.feed.today_watch
                if watch is not None and watch.stopped is not None and watch.dropped:
                    self.add_note(f"{watch.dropped} NSE symbols not scanned: the data path "
                                  f"refused today's candles for the first {watch.n} "
                                  f"({watch.stopped})")
                    if all(t.exchange == "NSE" for t in targets):
                        self.state = "failed"
                        self.message = watch.stopped
            if self.feed.incomplete:
                log.info("scanner: %d symbols lack their last session in history",
                         len(self.feed.incomplete))
            log.info("scanner: %s, %d/%d scanned, matches %s, %d errors, requests %s, "
                     "%.1f s", self.state, self.scanned, self.total, self.matches, self.errors,
                     self.requests, (self.clock() - self.started_at).total_seconds())
        except asyncio.CancelledError:
            self.state = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            self.state = "failed"
            self.message = str(exc) or type(exc).__name__
            if isinstance(exc, (BrokerError, ValueError, UniverseUnavailable)):
                log.error("scanner: scan failed: %s", self.message)
            else:
                log.exception("scanner: scan failed")
        finally:
            self.finished_at = self.clock()
            self.waiting_until = None
            self.eta_seconds = None if self.state != "done" else 0
            if heartbeat is not None:
                heartbeat.cancel()
                try:
                    await heartbeat
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            if self._hb_io is not None:   # cancelling did not stop its thread: let it finish
                try:
                    await self._hb_io
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            try:
                own = UPSTOX_REQUESTS.epochs(WINDOW, "scanner", external=False)
                await asyncio.to_thread(self.ledger_file.save, own)
            except Exception as exc:  # noqa: BLE001
                log.warning("scanner: could not save the request ledger (%s)", exc)
            try:
                await asyncio.to_thread(self.lock.release)
            except Exception:  # noqa: BLE001
                pass
            REQUEST_TAG.reset(tag_token)

    async def _heartbeat(self) -> None:
        i = 0
        while True:
            await asyncio.sleep(2.0)
            i += 1
            try:
                await self._hb_thread(self.lock.heartbeat)
            except Exception as exc:  # noqa: BLE001
                self._warn_once("heartbeat", "scanner: the scan-lock heartbeat failed (%s)", exc)
            if i % 5 == 0:
                try:
                    own = UPSTOX_REQUESTS.epochs(WINDOW, "scanner", external=False)
                    await self._hb_thread(self.ledger_file.save, own)
                except Exception as exc:  # noqa: BLE001
                    self._warn_once("ledger", "scanner: saving the request ledger failed (%s)", exc)

    async def _hb_thread(self, fn, *args) -> None:
        """Run fn in a thread, shielded: run()'s finally awaits it after cancelling the
        heartbeat, so the final ledger save and the lock release come after it."""
        self._hb_io = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        await asyncio.shield(self._hb_io)

    def _warn_once(self, key: str, msg: str, *args) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg, *args)

    async def _worker(self) -> None:
        while self._queue and not self._cancel.is_set() and not self._swapped:
            target = self._queue.popleft()
            try:
                result = await self._scan_one(target)
            except ScanCancelled:          # first: a cancelled wait is no result, not an error
                log.debug("scanner: %s not scanned (cancelled while waiting)", target.symbol)
                return
            except BrokerSwapped:
                self._swapped = True
                return
            except DataPathStopped:        # F14: no request was made for it
                log.debug("scanner: %s not scanned (the data path refuses today's candles)",
                          target.symbol)
                continue
            except BrokerError as exc:
                if not self.feed.still_pinned():
                    log.debug("scanner: %s dropped after a broker swap (%s)", target.symbol, exc)
                    self._swapped = True
                    return
                log.debug("scanner: %s: %s", target.symbol, exc)
                result = self._error_result(target, str(exc))
            except Exception as exc:  # noqa: BLE001
                if not self.feed.still_pinned():
                    log.debug("scanner: %s dropped after a broker swap (%s)", target.symbol, exc)
                    self._swapped = True
                    return
                log.exception("scanner: internal error on %s", target.symbol)
                result = self._error_result(target, f"internal error: {type(exc).__name__}: {exc}")
            if (result.status == "error" or result.data_error) and not self.feed.still_pinned():
                # an error caused by the swap (for example a request on the closed client)
                log.debug("scanner: %s dropped after a broker swap", target.symbol)
                self._swapped = True
                return
            self._add(result)

    def _error_result(self, target: Target, message: str) -> SymbolResult:
        return SymbolResult(seq=0, target=target, status="error", error=message, data_error=False,
                            synthetic=target.provider == "synthetic", ltp=None, prev_close=None,
                            change_pct=None, price_day=None, as_of=None,
                            notes=list(target.notes), sides={})

    def _add(self, result: SymbolResult) -> None:
        self._seq += 1
        result.seq = self._seq
        self.results.append(result)
        self.scanned += 1
        for side, sr in result.sides.items():
            if sr.signal:
                self.matches[side] = self.matches.get(side, 0) + 1
            self.skipped_rows += sum(1 for c in sr.rows if c.state == "skipped")
        if result.status == "error" or result.data_error:
            self.errors += 1
        if any(sr.na for sr in result.sides.values()):
            self.na_symbols += 1
        self._done_times.append(_time.monotonic())
        remaining = max(0, self.total - self.scanned)
        if remaining == 0:
            self.eta_seconds = 0
        elif len(self._done_times) >= 2:
            span = self._done_times[-1] - self._done_times[0]
            rate = (len(self._done_times) - 1) / span if span > 0 else 0.0
            self.eta_seconds = round(remaining / rate, 1) if rate > 0 else None

    async def _scan_one(self, t: Target) -> SymbolResult:
        feed = self.feed
        plan = self.plans[segment_class(t)]
        active = list(self.rows)
        lazy = self.evaluation_used == "lazy"
        try:
            today = await feed.today(t, plan.today_interval)
        except BrokerError as exc:
            return self._error_result(t, f"today's candles unavailable: {exc}")
        now = feed.clock()
        data = SymbolData(target=t, plan=plan, now=now, today=today, history={}, ltp=None,
                          close_time=feed.close_time(t, {}, plan))
        if today and session_open_now(t, data.close_time, now):
            data.ltp = await self.quotes.price(t, today.candles[-1].ts)
            if data.ltp is not None:
                data.ltp_at = self.quotes.fetched_at(t)
        results: dict[str, list[RowEval | None]] = {s: [None] * len(self.rows[s]) for s in active}

        def apply(found: dict) -> None:
            for (side, i), ev in found.items():
                if ev is not None:
                    results[side][i] = ev

        def states(side: str) -> list[bool | None]:
            return [None if ev is None else ev.result.state == "true" for ev in results[side]]

        def alive_sides() -> list[str]:
            return [s for s in active if rules.combine(self.rows[s], states(s)) is not False]

        local = [r for s in active for r in plan.refs[s] if r.session_local]
        if local:
            apply(await asyncio.to_thread(evaluate_refs, data, local, "today"))
        alive = alive_sides() if lazy else active
        data_error = False
        for source in plan.sources:
            if not alive:
                break
            pending = [r for s in alive for r in plan.refs[s]
                       if r.source == source.name and results[s][r.index] is None]
            if not pending:
                continue
            try:
                data.history[source.name] = await feed.history(t, source)
            except BrokerError as exc:
                for r in pending:
                    rr = rules.RowResult(r.index, rules.describe_rule(r.row), r.row["on"],
                                         "unavailable", f"data error: {exc}")
                    results[r.side][r.index] = RowEval(rr, 0, False)
                data_error = True
                continue
            new_close = feed.close_time(t, data.history, plan)
            if new_close != data.close_time:
                data.close_time = new_close
                data.calcs.clear()
            apply(await asyncio.to_thread(evaluate_refs, data, pending, "full"))
            if lazy:
                alive = alive_sides()

        sides: dict[str, SideResult] = {}
        for s in active:
            cells: list[RowCell] = []
            for ref in plan.refs[s]:
                ev = results[s][ref.index]
                if ev is None:
                    rr = rules.RowResult(ref.index, rules.describe_rule(ref.row), ref.row["on"],
                                         "skipped", SKIPPED_TEXT)
                    ev = RowEval(rr, 0, False)
                rr = ev.result
                cells.append(RowCell(state=rr.state, left=rr.left, right=rr.right,
                                     candle_ts=rr.candle_ts, bars=ev.bars,
                                     short_history=ev.short_history,
                                     detail=cell_detail(ref, rr, data)))
            st = [True if c.state == "true" else False if c.state in ("false", "unavailable")
                  else None for c in cells]
            sides[s] = SideResult(signal=rules.combine(self.rows[s], st) is True,
                                  met=sum(1 for c in cells if c.state == "true"),
                                  checked=sum(1 for c in cells if c.state != "skipped"),
                                  total=len(cells),
                                  na=sum(1 for c in cells if c.state == "unavailable"),
                                  rows=cells)

        ltp, price_day, prev_close, as_of = price_summary(data)
        change = (ltp / prev_close - 1.0) * 100.0 if ltp and prev_close else None
        has_bars = bool(today) or any(bool(s) for s in data.history.values())
        notes = list(t.notes) + list(feed.symbol_notes.get(t.key, []))
        if feed.today_needed(t) and not today:
            notes.append("no trades today")
        if price_day is not None and not session_open_now(t, data.close_time, now):
            self.add_note(f"{'MCX' if t.exchange == 'MCX' else 'NSE'} closed: values from the "
                          f"{price_day.day} {price_day:%b} session")
        if lazy and prev_close is None and ltp is not None and "day" not in data.history:
            notes.append("previous close not loaded (lazy mode)")
        day_hist = data.history.get("day")
        if t.exchange == "MCX" and day_hist:
            # design §5f: the near month's own history only; say why daily+ rows are n/a
            if any(ref.minutes >= DAY and c.state == "unavailable" and c.bars
                   for s in active for ref, c in zip(plan.refs[s], sides[s].rows)):
                daily = len(series_for(data, DAY, "full"))
                notes.append(f"{t.name or t.symbol}: {daily} daily bars since "
                             f"{day_hist.candles[0].ts.date().isoformat()}; continuous history "
                             "needs Upstox Plus")
        return SymbolResult(
            seq=0, target=t, status="ok" if has_bars else "no_data", error="",
            data_error=data_error, synthetic=t.provider == "synthetic", ltp=ltp,
            prev_close=prev_close, change_pct=change, price_day=price_day, as_of=as_of,
            notes=notes, sides=sides, series=dict(data.kept) if self.keep_series else None)

    # ---- status ----
    def _summary_notes(self) -> list[str]:
        notes = list(self.notes)
        inc = self.feed.incomplete
        if inc:
            end = next(iter(inc.values()))[1]
            day = f"{end.day} {end:%b}"
            early = self.clock() < datetime.combine(self.feed.day, time(9, 0), tzinfo=IST)
            if early:
                notes.append(f"{len(inc)} symbols have no {day} session in their history yet "
                             "(Upstox may not have published it; refetched after 30 minutes); "
                             "their values exclude it")
            else:
                notes.append(f"{len(inc)} symbols have no {day} session in their history (a "
                             "holiday, no trades, or published late)")
        return notes

    def summary(self) -> dict:
        until = self.waiting_until
        end = self.finished_at or self.clock()
        return {
            "id": self.id, "state": self.state, "trigger": self.trigger,
            "started_at": _iso(self.started_at), "finished_at": _iso(self.finished_at),
            "duration_seconds": round((end - self.started_at).total_seconds(), 1),
            "side": self.side, "sides": list(self.rows),
            "evaluation": self.evaluation, "evaluation_used": self.evaluation_used,
            "evaluation_reason": self.evaluation_reason,
            "universes": self.universes, "custom": self.custom, "skipped": self.skipped,
            "total": self.total, "scanned": self.scanned, "matches": dict(self.matches),
            "errors": self.errors, "na_symbols": self.na_symbols,
            "skipped_rows": self.skipped_rows, "requests": self.requests,
            "data_source": self.source_name, "synthetic": self.feed.synthetic,
            "estimate": self.estimate, "eta_seconds": self.eta_seconds,
            "waiting_until": (datetime.fromtimestamp(until, IST).isoformat(timespec="seconds")
                              if until is not None and math.isfinite(until) else None),
            "waiting_for_in_flight": until is not None and not math.isfinite(until),
            "notes": self._summary_notes(),
            "columns": {s: [{"index": i, "tf": r["tf"], "on": r["on"],
                             "text": rules.describe_rule(r), "label": short_label(r)}
                            for i, r in enumerate(rows)] for s, rows in self.rows.items()},
            "plan": {cls: p.as_dict(self.feed.day) for cls, p in self.plans.items()},
            "cache": {"hits": self.feed.cache.hits, "misses": self.feed.cache.misses},
            "budget": self.budget.snapshot(),
            "message": self.message,
        }

    def status(self, since: int = 0) -> dict:
        return {"scan": self.summary(),
                "results": [r.as_dict() for r in self.results if r.seq > since],
                "next": self._seq}


# ---------------------------------------------------------------- manager
class ScanManager:
    """One per app (app.state.scanner) or per CLI run. Exactly one of engine (the server:
    the data path is engine.broker, re-read per run and pinned for it) or broker (the
    CLI: fixed). clock is passed to every feed, quote book and cache it builds."""

    def __init__(self, cfg, engine=None, *, broker: Broker | None = None,
                 universes: UniverseStore | None = None,
                 clock: Callable[[], datetime] = now_ist) -> None:
        if (engine is None) == (broker is None):
            raise ValueError("ScanManager needs exactly one of engine or broker")
        self.cfg = cfg
        self.engine = engine
        self._broker = broker
        self.universes = universes or UniverseStore(cfg.cache_dir)
        self.clock = clock
        self.current: ScanJob | None = None
        self._owned: UpstoxData | None = None
        self.root = Path(cfg.cache_dir) / "scan"
        self.lock = RunLock(self.root / ".running")
        self.ledger_file = LedgerFile(self.root / "ledger.json")
        self._cloud_checked = False
        self._starting = False

    def data_broker(self) -> Broker:
        return self.engine.broker if self.engine is not None else self._broker

    def upstox(self) -> UpstoxData:
        found = find_upstox(self.data_broker())
        if found is not None:
            return found
        if self._owned is None:
            self._owned = UpstoxData(cache_dir=self.cfg.cache_dir,
                                     access_token=self.cfg.secrets.upstox_access_token)
        return self._owned

    @staticmethod
    def _dhan(pinned: Broker) -> DhanBroker | None:
        """The Dhan node whose quote API prices NSE when Dhan serves the candles (paper
        mode with a Dhan data broker, or a bare DhanBroker in live mode), else None."""
        node = data_node(pinned)
        return node if isinstance(node, DhanBroker) else None

    def _still_pinned(self, pinned: Broker) -> Callable[[], bool]:
        if self.engine is None:
            return lambda: True
        return lambda: self.engine.broker is pinned

    async def _load_ledger(self) -> None:
        UPSTOX_REQUESTS.set_external(await asyncio.to_thread(self.ledger_file.read_external))

    async def estimate(self, spec: ScanSpec) -> dict:
        await self._load_ledger()
        opts = self.cfg.scanner
        pinned = self.data_broker()
        today = self.clock().date()
        budget = Budget(UPSTOX_REQUESTS, "scanner:estimate", rate=opts.requests_per_second,
                        scanner_cap=opts.max_requests_per_30min)
        quotes = QuoteBook(upstox=self.upstox(), dhan=self._dhan(pinned), budget=budget,
                           clock=self.clock, still_pinned=lambda: True, note=lambda _text: None)
        feed = ScanFeed(broker=pinned, upstox=self.upstox(), universes=self.universes,
                        cache=HistoryCache(self.root, today, self.clock), budget=budget,
                        quotes=quotes, today=today, clock=self.clock,
                        still_pinned=lambda: True, note=lambda _text: None)
        expansion = await feed.expand(spec)
        plans = build_plans(spec, expansion.targets, today)
        quotes.plan(expansion.targets)
        available = available_now(UPSTOX_REQUESTS, scanner_cap=opts.max_requests_per_30min)
        return await compute_estimate(feed, expansion, plans, spec, opts, available=available,
                                      quote_batches=quotes.batches())

    async def load_universes(self, ids) -> dict[str, str]:
        """Load the named universes so info() knows their sizes (GET
        /api/scanner/universes?load=). Returns {id: error text} for the ones that failed."""
        errors: dict[str, str] = {}
        today = self.clock().date()
        for uid in ids:
            try:
                if uid in INDEX_UNIVERSES:
                    await self.universes.index_list(uid)
                elif uid == "fno":
                    master = await self.upstox().exchange_instruments("NSE")
                    names = [u for u in master.futures if ("NSE", u) in master.equities]
                    self.universes.note_derived(uid, len(names), today)
                elif uid == "mcx":
                    rows = await self.upstox().commodity_underlyings()
                    self.universes.note_derived(uid, len(rows), today)
            except (BrokerError, UniverseUnavailable, ValueError) as exc:
                errors[uid] = str(exc) or type(exc).__name__
        return errors

    def _cloud_notice(self) -> None:
        """Synchronous (run in a thread): Path.resolve stats the file system."""
        try:
            cache = Path(self.cfg.cache_dir).resolve()
            cloud = (Path.home() / "Library" / "CloudStorage").resolve()
        except OSError:
            return
        if cache.is_relative_to(cloud):
            log.info("scanner: the cache directory %s is inside a cloud-synced folder; a first "
                     "scan of the day writes about 1,000-1,500 small files there, which the "
                     "sync client uploads. Exclude cache/ from sync, or run Matheran from a "
                     "non-synced directory.", cache)

    async def start(self, spec: ScanSpec, *, keep_series: bool = False) -> ScanJob:
        job = self.current
        if job is not None and job.active:
            raise ScanBusy(f"a scan is already running (started {_hms(job.started_at)}, "
                           f"{job.scanned}/{job.total} scanned)")
        # Synchronous guard, set before the first await: a second start during the lock,
        # estimate or notice awaits below must not create a second job.
        if self._starting:
            raise ScanBusy("a scan is starting; try again in a moment")
        self._starting = True
        try:
            await self._finish_previous()
            return await self._start(spec, keep_series=keep_series)
        finally:
            self._starting = False

    async def _finish_previous(self) -> None:
        """The previous job turns inactive before its run() cleanup (heartbeat, ledger save,
        lock release) ends: wait for that cleanup, so the new run does not find this
        process's own lock still held."""
        job = self.current
        task = job.task if job is not None else None
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), 5.0)
        except TimeoutError:
            raise ScanBusy("the previous scan is still finishing; try again in a moment") from None
        except asyncio.CancelledError:
            if not task.done() or asyncio.current_task().cancelling():
                raise
        except Exception:  # noqa: BLE001  (run() handles its own errors; nothing to report)
            pass

    async def _start(self, spec: ScanSpec, *, keep_series: bool) -> ScanJob:
        job_id = secrets.token_hex(6)
        await asyncio.to_thread(self.lock.acquire, job_id)
        try:
            opts = self.cfg.scanner
            checked = None
            if spec.trigger == "auto":
                checked = await self.estimate(spec)
                req = checked["requests"]
                if req["minimum"] > checked["available"]:
                    raise ScanRefused(f"auto-rescan skipped: needs ≈{req['minimum']:,} requests, "
                                      f"{checked['available']:,} available")
                per_30 = req["repeat"] * 30 / int(spec.interval_minutes or 30)
                if per_30 > opts.max_requests_per_30min:
                    raise ScanRefused(f"auto-rescan skipped: every {spec.interval_minutes} minutes "
                                      f"needs ≈{per_30:,.0f} requests per 30 minutes, more than "
                                      f"the scanner cap ({opts.max_requests_per_30min:,})")
            if not self._cloud_checked:
                self._cloud_checked = True
                await asyncio.to_thread(self._cloud_notice)
            pinned = self.data_broker()
            today = self.clock().date()
            box: dict[str, ScanJob] = {}
            budget = Budget(UPSTOX_REQUESTS, f"scanner:{job_id}", rate=opts.requests_per_second,
                            scanner_cap=opts.max_requests_per_30min,
                            on_wait=lambda until: box["job"].on_wait(until),
                            cancelled=lambda: box["job"].cancel_requested())

            def note(text: str) -> None:
                box["job"].add_note(text)

            still = self._still_pinned(pinned)
            quotes = QuoteBook(upstox=self.upstox(), dhan=self._dhan(pinned), budget=budget,
                               clock=self.clock, still_pinned=still, note=note)
            feed = ScanFeed(broker=pinned, upstox=self.upstox(), universes=self.universes,
                            cache=HistoryCache(self.root, today, self.clock), budget=budget,
                            quotes=quotes, today=today, clock=self.clock, still_pinned=still,
                            note=note)
            job = ScanJob(spec, options=opts, feed=feed, budget=budget, quotes=quotes,
                          lock=self.lock, ledger_file=self.ledger_file, pinned_broker=pinned,
                          engine=self.engine, keep_series=keep_series, job_id=job_id,
                          clock=self.clock)
            box["job"] = job
            job.checked_estimate = checked
            job.task = asyncio.create_task(job.run(), name="matheran-scan")
        except BaseException:
            await asyncio.to_thread(self.lock.release)
            raise
        self.current = job
        return job

    def cancel(self) -> ScanJob:
        job = self.current
        if job is None or not job.active:
            raise ScanIdle("no scan is running")
        job.cancel()
        return job

    def status(self, since: int = 0, *, other: dict | None = None) -> dict:
        """Synchronous, no I/O. `other`: RunLock.holder(...) read by the caller in a thread,
        only when no job of this process is active."""
        job = self.current
        out = job.status(since) if job is not None else {
            "scan": {"state": "idle"}, "results": [], "next": 0}
        if other and (job is None or not job.active):
            out["scan"]["other"] = {**other, "message": busy_text(other)}
        return out

    async def budget_status(self) -> dict:
        await self._load_ledger()
        opts = self.cfg.scanner
        job = self.current
        in_flight = job.budget.in_flight() if job is not None and job.active else 0
        return {
            "used_scanner_30m": UPSTOX_REQUESTS.count(WINDOW, prefix="scanner"),
            "used_external_30m": UPSTOX_REQUESTS.count(WINDOW, prefix=UPSTOX_REQUESTS.EXTERNAL_TAG),
            "used_total_30m": UPSTOX_REQUESTS.count(WINDOW),
            "used_60s": UPSTOX_REQUESTS.count(60),
            "in_flight": in_flight,
            "caps": {"scanner_30m": opts.max_requests_per_30min, "total_30m": 1850,
                     "per_minute": 450},
            "available": available_now(UPSTOX_REQUESTS, scanner_cap=opts.max_requests_per_30min,
                                       in_flight=in_flight),
            "rate_per_second": opts.requests_per_second,
        }

    async def shutdown(self) -> None:
        job = self.current
        if job is not None and job.active and job.task is not None:
            job.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(job.task), 3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                job.task.cancel()
                try:
                    await job.task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            log.info("scanner: the running scan was cancelled at shutdown")
        if self._owned is not None:
            await self._owned.shutdown()
            self._owned = None
