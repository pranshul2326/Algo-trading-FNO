"""Technical indicators with TradingView (Pine v5) semantics.

Conventions that matter for matching a chart:
  * ta.rma  -> Wilder smoothing seeded with the SMA of the first `period` values.
  * ta.ema  -> seeded with the SMA of the first `period` values (not with the first value).
  * ta.atr  -> rma(true_range), and true range on the first bar is high - low.
  * Leading NaNs (e.g. feeding RSI into an EMA) are skipped, then the smoother is
    seeded from the first real value, which is what Pine does with `na` series.

Everything returns a float array the same length as the input, NaN-padded at the
front until the indicator has enough data to be defined.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

ArrayLike = Sequence[float] | np.ndarray


def _arr(values: ArrayLike) -> np.ndarray:
    return np.asarray(values, dtype=float)


def _skip_leading_nan(
    fn: Callable[[np.ndarray, int], np.ndarray], values: np.ndarray, period: int
) -> np.ndarray:
    """Run `fn` on the series after its leading NaN block, realigning the output."""
    out = np.full(len(values), np.nan)
    finite = np.flatnonzero(~np.isnan(values))
    if finite.size == 0:
        return out
    start = int(finite[0])
    out[start:] = fn(values[start:], period)
    return out


def sma(values: ArrayLike, period: int) -> np.ndarray:
    v = _arr(values)
    n = v.size
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    csum = np.cumsum(np.insert(v, 0, 0.0))
    out[period - 1 :] = (csum[period:] - csum[:-period]) / period
    return out


def rma(values: ArrayLike, period: int) -> np.ndarray:
    """Wilder's moving average, a.k.a. Pine's ta.rma."""
    v = _arr(values)
    n = v.size
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    out[period - 1] = v[:period].mean()
    alpha = 1.0 / period
    for i in range(period, n):
        prev = out[i - 1]
        out[i] = prev + alpha * (v[i] - prev)
    return out


def ema(values: ArrayLike, period: int) -> np.ndarray:
    """Pine's ta.ema: SMA-seeded exponential moving average."""
    v = _arr(values)
    n = v.size
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    out[period - 1] = v[:period].mean()
    k = 2.0 / (period + 1.0)
    for i in range(period, n):
        out[i] = v[i] * k + out[i - 1] * (1.0 - k)
    return out


def ema_of(values: ArrayLike, period: int) -> np.ndarray:
    """EMA of a series that may start with NaNs (e.g. an RSI series)."""
    return _skip_leading_nan(ema, _arr(values), period)


def rsi(close: ArrayLike, period: int = 14) -> np.ndarray:
    """Wilder RSI, matching Pine's ta.rsi."""
    c = _arr(close)
    n = c.size
    out = np.full(n, np.nan)
    if n < 2:
        return out

    delta = np.diff(c, prepend=np.nan)
    gain = np.where(delta > 0.0, delta, 0.0)
    loss = np.where(delta < 0.0, -delta, 0.0)
    gain[0] = np.nan
    loss[0] = np.nan

    avg_gain = _skip_leading_nan(rma, gain, period)
    avg_loss = _skip_leading_nan(rma, loss, period)

    defined = ~(np.isnan(avg_gain) | np.isnan(avg_loss))
    if not defined.any():
        return out

    g = avg_gain[defined]
    l = avg_loss[defined]
    vals = np.empty(g.size)

    both_flat = (g == 0.0) & (l == 0.0)
    no_loss = (l == 0.0) & (g > 0.0)
    normal = ~(both_flat | no_loss)

    vals[both_flat] = 50.0  # perfectly flat window: RS is 0/0, report neutral
    vals[no_loss] = 100.0
    rs = g[normal] / l[normal]
    vals[normal] = 100.0 - 100.0 / (1.0 + rs)

    out[defined] = vals
    return out


def true_range(high: ArrayLike, low: ArrayLike, close: ArrayLike) -> np.ndarray:
    h, l, c = _arr(high), _arr(low), _arr(close)
    prev_close = np.roll(c, 1)
    prev_close[0] = np.nan
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_close), np.abs(l - prev_close)))
    tr[0] = h[0] - l[0]  # Pine's ta.tr(true)
    return tr


def atr(high: ArrayLike, low: ArrayLike, close: ArrayLike, period: int = 14) -> np.ndarray:
    return rma(true_range(high, low, close), period)


def supertrend(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    period: int = 21,
    factor: float = 0.618,
) -> tuple[np.ndarray, np.ndarray]:
    """Pine's ta.supertrend.

    Returns (line, direction) where direction is -1 for an uptrend (line sits
    below price) and +1 for a downtrend. `price > supertrend` is therefore the
    same test as `direction == -1`.
    """
    h, l, c = _arr(high), _arr(low), _arr(close)
    n = c.size
    line = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    if n == 0:
        return line, direction

    atr_v = atr(h, l, c, period)
    hl2 = (h + l) / 2.0

    prev_upper = np.nan
    prev_lower = np.nan
    prev_line = np.nan
    prev_dir = np.nan

    for i in range(n):
        a = atr_v[i]
        if np.isnan(a):
            continue

        upper = hl2[i] + factor * a
        lower = hl2[i] - factor * a

        if not np.isnan(prev_lower):
            if not (lower > prev_lower or c[i - 1] < prev_lower):
                lower = prev_lower
        if not np.isnan(prev_upper):
            if not (upper < prev_upper or c[i - 1] > prev_upper):
                upper = prev_upper

        if np.isnan(prev_dir):
            # First bar where ATR exists: Pine seeds direction to 1 (downtrend).
            d = 1.0
        elif prev_line == prev_upper:
            d = -1.0 if c[i] > upper else 1.0
        else:
            d = 1.0 if c[i] < lower else -1.0

        cur_line = lower if d == -1.0 else upper

        line[i] = cur_line
        direction[i] = d

        prev_upper, prev_lower = upper, lower
        prev_line, prev_dir = cur_line, d

    return line, direction


@dataclass(frozen=True, slots=True)
class SupertrendState:
    """Supertrend after one more bar: what the next bar's calculation reads.

    The same recursion as supertrend() written one bar at a time, so a bar that is
    still forming can be evaluated from the last closed bar's state without
    recomputing the series. Used for a higher timeframe's Supertrend on a lower
    timeframe chart.
    """

    bars: int
    tr_sum: float       # true ranges summed while the ATR is still seeding
    atr: float          # NaN until `period` bars have been seen
    upper: float
    lower: float
    line: float
    direction: float    # -1 uptrend, +1 downtrend, NaN until defined
    close: float


def supertrend_step(
    prev: SupertrendState | None,
    high: float,
    low: float,
    close: float,
    period: int,
    factor: float,
) -> SupertrendState:
    """One bar of Pine's ta.supertrend, from the previous bar's state."""
    nan = float("nan")
    if prev is None:
        tr = high - low
        bars = 1
        tr_sum = 0.0
    else:
        pc = prev.close
        tr = max(high - low, abs(high - pc), abs(low - pc))
        bars = prev.bars + 1
        tr_sum = prev.tr_sum
    if bars < period:
        return SupertrendState(bars, tr_sum + tr, nan, nan, nan, nan, nan, close)
    if bars == period:
        atr_v = (tr_sum + tr) / period
    else:
        atr_v = prev.atr + (tr - prev.atr) / period  # ta.rma
    hl2 = (high + low) / 2.0
    upper = hl2 + factor * atr_v
    lower = hl2 - factor * atr_v
    seeded = prev is not None and not np.isnan(prev.atr)
    if seeded:
        if not (lower > prev.lower or prev.close < prev.lower):
            lower = prev.lower
        if not (upper < prev.upper or prev.close > prev.upper):
            upper = prev.upper
        if prev.line == prev.upper:
            d = -1.0 if close > upper else 1.0
        else:
            d = 1.0 if close < lower else -1.0
    else:
        d = 1.0  # Pine seeds the first defined bar as a downtrend
    line = lower if d == -1.0 else upper
    return SupertrendState(bars, 0.0, atr_v, upper, lower, line, d, close)


def supertrend_states(
    high: ArrayLike, low: ArrayLike, close: ArrayLike, period: int, factor: float
) -> list[SupertrendState]:
    h, l, c = _arr(high), _arr(low), _arr(close)
    out: list[SupertrendState] = []
    state: SupertrendState | None = None
    for i in range(c.size):
        state = supertrend_step(state, float(h[i]), float(l[i]), float(c[i]), period, factor)
        out.append(state)
    return out


def zema(values: ArrayLike, period: int) -> np.ndarray:
    """Zero-lag EMA (ZLEMA): an EMA of the price pushed forward by the EMA's own lag.

        lag  = (period - 1) // 2
        zema = EMA(price + (price - price[lag]), period)

    The de-lagged form used by TradingView community scripts, TA-Lib and pandas-ta,
    with the same SMA-seeded EMA as ta.ema. Defined from bar lag + period - 1.
    """
    v = _arr(values)
    n = v.size
    lag = max(0, (int(period) - 1) // 2)
    shifted = np.full(n, np.nan)
    if lag == 0:
        shifted = v.copy()
    elif n > lag:
        shifted[lag:] = v[:-lag]
    return ema_of(v + (v - shifted), int(period))


def dmi(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    di_period: int = 14,
    adx_period: int = 14,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pine's ta.dmi. Returns (adx, plus_di, minus_di)."""
    h, l, c = _arr(high), _arr(low), _arr(close)
    n = c.size
    if n == 0:
        empty = np.full(0, np.nan)
        return empty, empty, empty

    up = np.diff(h, prepend=np.nan)
    down = -np.diff(l, prepend=np.nan)

    plus_dm = np.where((up > down) & (up > 0.0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0.0), down, 0.0)
    plus_dm[0] = np.nan
    minus_dm[0] = np.nan

    trur = rma(true_range(h, l, c), di_period)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * _skip_leading_nan(rma, plus_dm, di_period) / trur
        minus_di = 100.0 * _skip_leading_nan(rma, minus_dm, di_period) / trur

    total = plus_di + minus_di
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = np.abs(plus_di - minus_di) / np.where(total == 0.0, 1.0, total)
    adx_v = 100.0 * _skip_leading_nan(rma, dx, adx_period)
    return adx_v, plus_di, minus_di


def adx(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    di_period: int = 14,
    adx_period: int = 14,
) -> np.ndarray:
    return dmi(high, low, close, di_period, adx_period)[0]


def session_vwap(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    volume: ArrayLike,
    session_ids: Sequence[object] | None = None,
) -> np.ndarray:
    """Volume weighted average price using the typical price, reset per session.

    `session_ids` marks which bars belong to the same trading day; when omitted
    the whole series is treated as one session. Bars with no volume carry the
    previous VWAP forward (index candles report zero volume).
    """
    h, l, c, v = _arr(high), _arr(low), _arr(close), _arr(volume)
    n = c.size
    out = np.full(n, np.nan)
    if n == 0:
        return out

    typical = (h + l + c) / 3.0
    ids = list(session_ids) if session_ids is not None else [0] * n

    # Indices report no volume at all. Volume weighting would then pin VWAP to the
    # first bar forever, so those sessions fall back to a running mean of the typical
    # price. Sessions that do have volume are unaffected, including the individual
    # zero-volume minutes that occur in quiet stretches of a real session.
    volume_by_session: dict[object, float] = {}
    for i in range(n):
        vol = v[i] if np.isfinite(v[i]) else 0.0
        volume_by_session[ids[i]] = volume_by_session.get(ids[i], 0.0) + max(0.0, vol)

    cum_pv = 0.0
    cum_v = 0.0
    cum_typical = 0.0
    bars = 0
    last_id = object()
    last_vwap = np.nan

    for i in range(n):
        if ids[i] != last_id:
            cum_pv = cum_v = cum_typical = 0.0
            bars = 0
            last_vwap = np.nan
            last_id = ids[i]

        cum_typical += typical[i]
        bars += 1

        if volume_by_session.get(ids[i], 0.0) <= 0.0:
            out[i] = cum_typical / bars
            continue

        vol = v[i] if np.isfinite(v[i]) else 0.0
        if vol > 0.0:
            cum_pv += typical[i] * vol
            cum_v += vol

        if cum_v > 0.0:
            last_vwap = cum_pv / cum_v
        elif np.isnan(last_vwap):
            last_vwap = typical[i]

        out[i] = last_vwap

    return out


def crossed_above(a: np.ndarray, b: np.ndarray, index: int) -> bool:
    """True when series `a` crossed from at-or-below `b` to above it at `index`."""
    if index < 1:
        return False
    prev_a, prev_b, cur_a, cur_b = a[index - 1], b[index - 1], a[index], b[index]
    if any(np.isnan(x) for x in (prev_a, prev_b, cur_a, cur_b)):
        return False
    return bool(prev_a <= prev_b and cur_a > cur_b)


def crossed_below(a: np.ndarray, b: np.ndarray, index: int) -> bool:
    if index < 1:
        return False
    prev_a, prev_b, cur_a, cur_b = a[index - 1], b[index - 1], a[index], b[index]
    if any(np.isnan(x) for x in (prev_a, prev_b, cur_a, cur_b)):
        return False
    return bool(prev_a >= prev_b and cur_a < cur_b)


def last_value(series: np.ndarray) -> float | None:
    """Most recent non-NaN value, or None."""
    finite = np.flatnonzero(~np.isnan(series))
    if finite.size == 0:
        return None
    return float(series[finite[-1]])
