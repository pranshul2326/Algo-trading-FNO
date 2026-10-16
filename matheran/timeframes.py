"""Timeframes, and loading candles at any of them.

One table drives every timeframe picker in the app, the API's validation and the
engine, so a timeframe offered on a chart is one a watch can trade on.

Intraday bars are anchored at the session open: a 2-hour bar spans 09:15-11:15,
11:15-13:15, 13:15-15:15, and the last one of the day is the 15:15-15:30 remainder.
A day bar is one session, a week bar Monday to Friday, a month bar the calendar
month. See candles.resample and candles.bar_end.

Where the candles come from:

  * today, always from the 1-minute feed the engine already polls (and caches), so the
    bar still forming is priced exactly as the engine prices it;
  * earlier sessions, from the provider's history at the coarsest interval that still
    divides the timeframe - 30-minute candles for a 2-hour chart, one candle per
    session for a weekly one - so a long timeframe reaches back months without pulling
    every minute of it. The five sessions before today come from the 1-minute feed too.

A provider without a history service still works: everything is then built from the
1-minute feed, which covers today and the five sessions before it.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime

from .brokers.base import BrokerError
from .candles import DAY, MONTH, WEEK, CandleSeries, resample
from .timeutil import now_ist, previous_trading_day, session_close, session_open

log = logging.getLogger(__name__)

__all__ = [
    "DAY", "WEEK", "MONTH", "TIMEFRAMES", "MINUTES", "CODE_MINUTES",
    "normalise", "minutes_of", "code_of", "label_of", "info", "load_series",
    "sessions_for", "bars_per_session",
]

# (code, minutes, label). Codes are case sensitive: 1m is a minute, 1M a month.
TIMEFRAMES: tuple[tuple[str, int, str], ...] = (
    ("1m", 1, "1 min"),
    ("3m", 3, "3 min"),
    ("5m", 5, "5 min"),
    ("9m", 9, "9 min"),
    ("15m", 15, "15 min"),
    ("30m", 30, "30 min"),
    ("1h", 60, "1 hour"),
    ("2h", 120, "2 hours"),
    ("1D", DAY, "1 day"),
    ("1W", WEEK, "1 week"),
    ("1M", MONTH, "1 month"),
)
CODE_MINUTES: dict[str, int] = {code: minutes for code, minutes, _ in TIMEFRAMES}
MINUTES: tuple[int, ...] = tuple(minutes for _, minutes, _ in TIMEFRAMES)
_CODES = {minutes: code for code, minutes, _ in TIMEFRAMES}
_LABELS = {minutes: label for _, minutes, label in TIMEFRAMES}
# Older spellings, so saved chart layouts and bookmarks keep working.
ALIASES = {
    "60m": "1h", "120m": "2h", "1H": "1h", "2H": "2h",
    "1d": "1D", "D": "1D", "1w": "1W", "W": "1W", "M": "1M", "1mo": "1M",
}


def normalise(code: str | None) -> str | None:
    """The canonical code for a timeframe string, or None if it is not one."""
    text = (code or "").strip()
    if text in CODE_MINUTES:
        return text
    return ALIASES.get(text)


def minutes_of(code: str | None) -> int | None:
    canonical = normalise(code)
    return CODE_MINUTES[canonical] if canonical else None


def code_of(minutes: int) -> str:
    return _CODES.get(int(minutes), f"{int(minutes)}m")


def label_of(minutes: int) -> str:
    return _LABELS.get(int(minutes), f"{int(minutes)} min")


def info() -> list[dict]:
    """The table as the pages read it."""
    return [{"id": code, "minutes": minutes, "label": label} for code, minutes, label in TIMEFRAMES]


# ----------------------------------------------------------------- loading
MAX_INTRADAY_SESSIONS = 200          # about ten months of trading days
MAX_DAILY_SESSIONS = 20 * 250        # twenty years of sessions
RECENT_SESSIONS = 6                  # what intraday_candles covers: today and five before


def bars_per_session(minutes: int, segment: str = "NSE_EQ") -> int:
    day = date(2026, 1, 5)  # any weekday; only the session length matters
    length = (session_close(segment, day) - session_open(segment, day)).total_seconds() / 60
    return max(1, math.ceil(length / max(1, minutes)))


def sessions_for(minutes: int, bars: int, segment: str = "NSE_EQ") -> int:
    """Trading sessions of history needed for `bars` bars of this timeframe."""
    bars = max(1, int(bars))
    if minutes < DAY:
        need = math.ceil(bars / bars_per_session(minutes, segment)) + 1
        return max(RECENT_SESSIONS, min(need, MAX_INTRADAY_SESSIONS))
    per_bar = 1 if minutes < WEEK else 5 if minutes < MONTH else 21
    # Weekdays stand in for sessions, and holidays make a few of them empty: 5% spare.
    need = math.ceil((bars + 1) * per_bar * 1.05)
    return max(RECENT_SESSIONS, min(need, MAX_DAILY_SESSIONS))


def _history_interval(minutes: int) -> int:
    """The coarsest history interval that still divides the timeframe."""
    if minutes >= DAY:
        return DAY
    for step in (30, 15):
        if minutes % step == 0:
            return step
    return 1


def _merge(*parts: CandleSeries) -> CandleSeries:
    """Bars keyed by start time; later parts win where they overlap."""
    by_ts = {}
    for part in parts:
        for c in part.candles:
            by_ts[c.ts] = c
    return CandleSeries([by_ts[ts] for ts in sorted(by_ts)])


# Public name for other modules (the scanner merges history with today's bars).
merge_series = _merge


async def load_series(
    broker,
    instrument,
    minutes: int,
    *,
    bars: int,
    now: datetime | None = None,
) -> CandleSeries:
    """Candles at `minutes`, oldest first, reaching back at least `bars` bars where the
    provider's history allows. The bar still forming is included; callers that act on
    closed bars drop it with candles.drop_forming."""
    now = now or now_ist()
    today = now.date()
    segment = instrument.segment
    minutes = int(minutes)

    recent = await broker.intraday_candles(instrument, today, 1)
    sessions = sessions_for(minutes, bars, segment)
    if minutes < DAY and sessions <= RECENT_SESSIONS:
        return resample(recent, minutes, segment)

    interval = _history_interval(minutes)
    start = previous_trading_day(today, sessions)
    end = previous_trading_day(today, 1)
    history = None
    try:
        history = await broker.history_candles(instrument, interval, start, end)
    except BrokerError as exc:
        log.info("timeframes: no history for %s at %s (%s); using the recent sessions only",
                 instrument.symbol, code_of(minutes), exc)

    base = DAY if minutes >= DAY else minutes
    recent_bars = resample(recent, base, segment)
    if not history:
        return resample(recent_bars, minutes, segment) if minutes > DAY else recent_bars
    combined = _merge(resample(history, base, segment), recent_bars)
    return resample(combined, minutes, segment) if minutes > DAY else combined
