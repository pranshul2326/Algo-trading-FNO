"""Candle container, epoch normalisation and timeframe resampling."""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Sequence

import numpy as np

from .timeutil import IST, session_close, session_open

log = logging.getLogger(__name__)

# Timeframes of a session or longer, in minutes. Only DAY is an exact length: a week
# runs Monday to Friday and a month by the calendar, whatever their minute count.
DAY = 1440
WEEK = 7 * DAY
MONTH = 30 * DAY

# Trading conditions support the provider's regular OHLC candles and a full-series
# Heikin Ashi transform. ``normal`` is deliberately the default so every existing
# config, saved watch and API client keeps its previous behaviour.
CANDLE_TYPES = ("normal", "heikin_ashi")
CANDLE_TYPE_LABELS = {"normal": "Normal candle", "heikin_ashi": "Heikin Ashi"}


@dataclass(frozen=True, slots=True)
class Candle:
    ts: datetime  # IST, start of the bucket
    open: float
    high: float
    low: float
    close: float
    volume: float
    # Open interest is a level, not a flow: it is carried as the value standing at
    # the end of the bucket, never summed. Zero for cash-segment instruments.
    oi: float = 0.0

    def as_dict(self) -> dict:
        return {
            "ts": self.ts.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "oi": self.oi,
        }


class CandleSeries:
    """A list of candles plus column views for the indicator functions."""

    __slots__ = ("candles", "_cols")

    def __init__(self, candles: Sequence[Candle]):
        self.candles = list(candles)
        self._cols: dict[str, np.ndarray] = {}

    def __len__(self) -> int:
        return len(self.candles)

    def __bool__(self) -> bool:
        return bool(self.candles)

    def _col(self, name: str) -> np.ndarray:
        if name not in self._cols:
            self._cols[name] = np.array([getattr(c, name) for c in self.candles], dtype=float)
        return self._cols[name]

    @property
    def open(self) -> np.ndarray:
        return self._col("open")

    @property
    def high(self) -> np.ndarray:
        return self._col("high")

    @property
    def low(self) -> np.ndarray:
        return self._col("low")

    @property
    def close(self) -> np.ndarray:
        return self._col("close")

    @property
    def volume(self) -> np.ndarray:
        return self._col("volume")

    @property
    def oi(self) -> np.ndarray:
        return self._col("oi")

    @property
    def session_ids(self) -> list:
        return [c.ts.date() for c in self.candles]

    @property
    def last(self) -> Candle | None:
        return self.candles[-1] if self.candles else None


def normalize_candle_type(value, field: str = "candle_type") -> str:
    """Return the canonical trading candle type, accepting common spellings."""
    text = "normal" if value is None else str(value).strip().lower().replace("-", "_").replace(" ", "_")
    text = {"candles": "normal", "haikin_ashi": "heikin_ashi"}.get(text, text)
    if text not in CANDLE_TYPES:
        raise ValueError(f"{field} must be normal or heikin_ashi, got {value!r}")
    return text


def apply_candle_type(series: CandleSeries, candle_type: str | None) -> CandleSeries:
    """Use regular candles or transform the complete series to Heikin Ashi.

    The transform keeps full precision and preserves timestamps, volume and open
    interest. Callers must pass all available history—not only the newest candle—
    because each Heikin Ashi open depends on the previous transformed candle.
    """
    mode = normalize_candle_type(candle_type)
    if mode == "normal" or not series:
        return series

    out: list[Candle] = []
    previous_open: float | None = None
    previous_close: float | None = None
    for candle in series.candles:
        close = (candle.open + candle.high + candle.low + candle.close) / 4.0
        open_ = (
            (candle.open + candle.close) / 2.0
            if previous_open is None or previous_close is None
            else (previous_open + previous_close) / 2.0
        )
        out.append(Candle(
            ts=candle.ts,
            open=open_,
            high=max(candle.high, open_, close),
            low=min(candle.low, open_, close),
            close=close,
            volume=candle.volume,
            oi=candle.oi,
        ))
        previous_open, previous_close = open_, close
    return CandleSeries(out)


IST_OFFSET = timedelta(hours=5, minutes=30)


def _outside_session(times: list[datetime], segment: str) -> int:
    """How many bars fall outside their exchange session window."""
    bad = 0
    for t in times:
        open_t = session_open(segment, t.date())
        close_t = session_close(segment, t.date())
        if t < open_t or t > close_t:
            bad += 1
    return bad


def normalise_epochs(epochs: Iterable[float], segment: str = "NSE_EQ") -> list[datetime]:
    """Convert broker epoch seconds to IST datetimes.

    Brokers are inconsistent about whether chart epochs are true UTC or already
    shifted to IST wall-clock, and getting it wrong moves every candle by 5.5
    hours, which silently wrecks VWAP (wrong session) and candle bucketing.

    Rather than trusting one convention, all three readings are scored by how many
    bars land outside the exchange session window; the cleanest wins, ties going
    to the plain reading.
    """
    raw = [float(e) for e in epochs]
    if not raw:
        return []

    plain = [datetime.fromtimestamp(e, tz=IST) for e in raw]
    candidates = {
        "utc": plain,
        "shift_forward": [d + IST_OFFSET for d in plain],
        "shift_back": [d - IST_OFFSET for d in plain],
    }
    scored = {name: _outside_session(times, segment) for name, times in candidates.items()}
    best = min(scored, key=lambda name: (scored[name], name != "utc"))
    if best != "utc":
        log.warning(
            "candles: %s epochs do not sit in the %s session (%d/%d bars outside); "
            "applying %s. Verify your broker's timestamp convention.",
            segment,
            segment,
            scored["utc"],
            len(raw),
            best,
        )
    return candidates[best]


def build_candles(
    *,
    timestamps: Iterable[float],
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    segment: str = "NSE_EQ",
    open_interest: Sequence[float] | None = None,
) -> CandleSeries:
    """Build a sorted 1-minute series from the broker's column-oriented payload."""
    times = normalise_epochs(timestamps, segment)
    oi_col = open_interest or []
    rows = []
    for i, ts in enumerate(times):
        try:
            rows.append(
                Candle(
                    ts=ts,
                    open=float(open_[i]),
                    high=float(high[i]),
                    low=float(low[i]),
                    close=float(close[i]),
                    volume=float(volume[i]) if i < len(volume) else 0.0,
                    oi=float(oi_col[i]) if i < len(oi_col) else 0.0,
                )
            )
        except (IndexError, TypeError, ValueError):
            continue
    rows.sort(key=lambda c: c.ts)
    # Drop duplicate timestamps, keeping the last occurrence.
    deduped: list[Candle] = []
    for c in rows:
        if deduped and deduped[-1].ts == c.ts:
            deduped[-1] = c
        else:
            deduped.append(c)
    return CandleSeries(deduped)


def _period_start(day: date, minutes: int) -> date:
    """First calendar day of the day, week (Monday) or month that `day` falls in."""
    if minutes >= MONTH:
        return day.replace(day=1)
    if minutes >= WEEK:
        return day - timedelta(days=day.weekday())
    return day


def _merge(start: datetime, group: list[Candle]) -> Candle:
    return Candle(
        ts=start,
        open=group[0].open,
        high=max(c.high for c in group),
        low=min(c.low for c in group),
        close=group[-1].close,
        volume=sum(c.volume for c in group),
        # A level, so the closing value wins rather than a sum.
        oi=group[-1].oi,
    )


def resample(series: CandleSeries, minutes: int, segment: str = "NSE_EQ") -> CandleSeries:
    """Aggregate candles into `minutes` buckets anchored at the session open.

    Intraday buckets restart every session, so a 2-hour bar spans 09:15-11:15 and the
    last one of the day is the 15:15-15:30 remainder. A day bar is one session, a week
    bar Monday to Friday and a month bar the calendar month; each is stamped with the
    session open of its first calendar day. The input may be 1-minute candles or any
    coarser candles anchored the same way, including one candle per session.
    """
    if minutes <= 1 or not series:
        return series

    buckets: dict[datetime, list[Candle]] = {}
    order: list[datetime] = []
    for c in series.candles:
        day = c.ts.date()
        if minutes >= DAY:
            start = session_open(segment, _period_start(day, minutes))
        else:
            anchor = session_open(segment, day)
            offset = int((c.ts - anchor).total_seconds() // 60)
            start = anchor + timedelta(minutes=(offset // minutes) * minutes)
        if start not in buckets:
            buckets[start] = []
            order.append(start)
        buckets[start].append(c)

    out = [_merge(start, buckets[start]) for start in order]
    out.sort(key=lambda c: c.ts)
    return CandleSeries(out)


def _last_weekday_of_month(day: date) -> date:
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    while last.weekday() >= 5:
        last -= timedelta(days=1)
    return last


def bar_end(
    ts: datetime, minutes: int, segment: str = "NSE_EQ", close_time: time | None = None
) -> datetime:
    """When the bar that starts at `ts` closes.

    An intraday bar closes after `minutes`, or at the session close if that comes
    first (the 15:15 two-hour bar closes at 15:30). A day bar closes at its session
    close, a week bar at Friday's and a month bar at its last weekday's. Exchange
    holidays are not modelled. `close_time`, when given, replaces the segment's
    session close (MCX closes at 23:30 or 23:55 depending on US daylight saving).
    """

    def closes(d: date) -> datetime:
        if close_time is None:
            return session_close(segment, d)
        return datetime.combine(d, close_time, tzinfo=IST)

    day = ts.date()
    if minutes >= MONTH:
        return closes(_last_weekday_of_month(day))
    if minutes >= WEEK:
        return closes(day + timedelta(days=4 - day.weekday()))
    if minutes >= DAY:
        return closes(day)
    end = ts + timedelta(minutes=minutes)
    close = closes(day)
    # Only clipped when the bar really sits inside the session; data stamped outside
    # it (a feed that runs late) keeps its nominal length.
    return close if ts < close < end else end


def drop_forming(
    series: CandleSeries,
    minutes: int,
    now: datetime,
    segment: str = "NSE_EQ",
    close_time: time | None = None,
) -> tuple[CandleSeries, Candle | None]:
    """Split off the candle that is still being built.

    Signals must only ever be evaluated on closed candles, otherwise a condition
    can appear and vanish inside the same bar.
    """
    if not series:
        return series, None
    last = series.candles[-1]
    if bar_end(last.ts, minutes, segment, close_time) > now:
        return CandleSeries(series.candles[:-1]), last
    return series, None
