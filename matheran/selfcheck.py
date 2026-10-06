"""Pre-flight checks. Run this before you trust the engine with money.

Each indicator is compared against an independently written, deliberately naive
reference implementation, plus a set of invariants that must hold on any input.
"""

from __future__ import annotations

import random
from datetime import timedelta

import numpy as np

from .candles import DAY, MONTH, WEEK, Candle, CandleSeries, bar_end, drop_forming, resample
from .config import StrategyConfig
from .indicators import (
    adx,
    crossed_above,
    ema,
    ema_of,
    rma,
    rsi,
    session_vwap,
    supertrend,
    supertrend_states,
    supertrend_step,
    true_range,
    zema,
)
from .models import round_to_tick
from .strategy import Indicators, evaluate_entry, evaluate_exit
from .timeutil import session_close, session_open


# ----------------------------------------------------------------- references
def ref_rma(values: list[float], period: int) -> list[float]:
    out = [float("nan")] * len(values)
    if len(values) < period:
        return out
    acc = sum(values[:period]) / period
    out[period - 1] = acc
    for i in range(period, len(values)):
        acc = acc + (values[i] - acc) / period
        out[i] = acc
    return out


def ref_ema(values: list[float], period: int) -> list[float]:
    out = [float("nan")] * len(values)
    if len(values) < period:
        return out
    acc = sum(values[:period]) / period
    out[period - 1] = acc
    k = 2.0 / (period + 1.0)
    for i in range(period, len(values)):
        acc = values[i] * k + acc * (1.0 - k)
        out[i] = acc
    return out


def ref_rsi(close: list[float], period: int) -> list[float]:
    gains, losses = [], []
    for i in range(1, len(close)):
        d = close[i] - close[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = ref_rma(gains, period)
    al = ref_rma(losses, period)
    out = [float("nan")] * len(close)
    for i, (g, l) in enumerate(zip(ag, al), start=1):
        if g != g or l != l:
            continue
        if l == 0.0 and g == 0.0:
            out[i] = 50.0
        elif l == 0.0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + g / l)
    return out


def ref_true_range(h: list[float], l: list[float], c: list[float]) -> list[float]:
    out = [h[0] - l[0]]
    for i in range(1, len(c)):
        out.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return out


def ref_zema(values: list[float], period: int) -> list[float]:
    """EMA (SMA-seeded) of price + (price - price[lag]), lag = (period - 1) // 2."""
    n = len(values)
    lag = (period - 1) // 2
    out = [float("nan")] * n
    delagged = [values[i] + (values[i] - values[i - lag]) for i in range(lag, n)]
    if len(delagged) < period:
        return out
    acc = sum(delagged[:period]) / period
    out[lag + period - 1] = acc
    k = 2.0 / (period + 1.0)
    for j in range(period, len(delagged)):
        acc = delagged[j] * k + acc * (1.0 - k)
        out[lag + j] = acc
    return out


def _days_series(day0, sessions: int, seed: int = 11) -> CandleSeries:
    """1-minute candles over `sessions` weekdays from `day0`, a full session each."""
    rng = random.Random(seed)
    price = 500.0
    out: list[Candle] = []
    d = day0
    made = 0
    while made < sessions:
        if d.weekday() < 5:
            t = session_open("NSE_EQ", d)
            end = session_close("NSE_EQ", d)
            while t < end:
                o = price
                c = max(1.0, o + rng.gauss(0, 0.4))
                out.append(Candle(ts=t, open=o, high=max(o, c) + 0.1, low=min(o, c) - 0.1, close=c,
                                  volume=float(rng.randint(10, 999))))
                price = c
                t += timedelta(minutes=1)
            made += 1
        d += timedelta(days=1)
    return CandleSeries(out)


# ---------------------------------------------------------------------- data
def synthetic_ohlc(n: int = 400, seed: int = 7) -> tuple[list, list, list, list, list]:
    rng = random.Random(seed)
    price = 1000.0
    o, h, l, c, v = [], [], [], [], []
    for _ in range(n):
        op = price
        moves = [price + rng.gauss(0, 3.0) for _ in range(4)]
        cl = moves[-1]
        o.append(round(op, 2))
        h.append(round(max([op, *moves]), 2))
        l.append(round(min([op, *moves]), 2))
        c.append(round(cl, 2))
        v.append(float(rng.randint(100, 9000)))
        price = cl
    return o, h, l, c, v


def _series(o, h, l, c, v, day) -> CandleSeries:
    start = session_open("NSE_EQ", day)
    return CandleSeries(
        [
            Candle(ts=start + timedelta(minutes=i), open=o[i], high=h[i], low=l[i], close=c[i], volume=v[i])
            for i in range(len(c))
        ]
    )


# -------------------------------------------------------------------- checks
def run_checks() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    o, h, l, c, v = synthetic_ohlc(400)
    hn, ln, cn = np.array(h), np.array(l), np.array(c)

    # RMA / EMA against the naive references
    for period in (9, 14, 21):
        mine = rma(c, period)
        theirs = ref_rma(c, period)
        diff = np.nanmax(np.abs(mine - np.array(theirs)))
        check(f"rma(period={period}) matches reference", diff < 1e-9, f"max diff {diff:.2e}")

        mine = ema(c, period)
        theirs = ref_ema(c, period)
        diff = np.nanmax(np.abs(mine - np.array(theirs)))
        check(f"ema(period={period}) matches reference", diff < 1e-9, f"max diff {diff:.2e}")

    # RSI against the naive reference
    for period in (14, 21):
        mine = rsi(c, period)
        theirs = np.array(ref_rsi(c, period))
        both = ~(np.isnan(mine) | np.isnan(theirs))
        diff = np.max(np.abs(mine[both] - theirs[both]))
        check(f"rsi(period={period}) matches reference", diff < 1e-9, f"max diff {diff:.2e}")
        check(
            f"rsi(period={period}) stays within 0..100",
            bool(np.all((mine[~np.isnan(mine)] >= 0) & (mine[~np.isnan(mine)] <= 100))),
        )
        first = int(np.flatnonzero(~np.isnan(mine))[0])
        check(f"rsi(period={period}) first value at bar {period}", first == period, f"got {first}")

    # true range
    diff = np.nanmax(np.abs(true_range(hn, ln, cn) - np.array(ref_true_range(h, l, c))))
    check("true_range matches reference", diff < 1e-9, f"max diff {diff:.2e}")

    # EMA of a flat series is the same constant
    flat = [42.0] * 80
    check("ema of a constant series is constant", abs(ema(flat, 21)[-1] - 42.0) < 1e-12)
    check("rma of a constant series is constant", abs(rma(flat, 21)[-1] - 42.0) < 1e-12)

    # RSI extremes
    rising = list(np.linspace(100, 200, 90))
    check("rsi of a strictly rising series is 100", abs(rsi(rising, 21)[-1] - 100.0) < 1e-9)
    falling = list(np.linspace(200, 100, 90))
    check("rsi of a strictly falling series is 0", abs(rsi(falling, 21)[-1] - 0.0) < 1e-9)

    # EMA over a NaN-prefixed series starts at the right bar
    rsi21 = rsi(c, 21)
    sig = ema_of(rsi21, 21)
    first_rsi = int(np.flatnonzero(~np.isnan(rsi21))[0])
    first_sig = int(np.flatnonzero(~np.isnan(sig))[0])
    check(
        "ema_of skips the NaN prefix (signal starts 20 bars after RSI)",
        first_sig == first_rsi + 20,
        f"rsi@{first_rsi}, signal@{first_sig}",
    )

    # Supertrend geometry: the line must sit on the correct side of price
    line, direction = supertrend(hn, ln, cn, 21, 0.618)
    valid = ~np.isnan(line)
    up = valid & (direction == -1)
    down = valid & (direction == 1)
    check(
        "supertrend sits below close in an uptrend",
        bool(np.all(line[up] <= cn[up] + 1e-9)),
        f"{int(up.sum())} up bars",
    )
    check(
        "supertrend sits above close in a downtrend",
        bool(np.all(line[down] >= cn[down] - 1e-9)),
        f"{int(down.sum())} down bars",
    )
    check(
        "supertrend direction is only -1 or +1",
        bool(np.all(np.isin(direction[valid], (-1.0, 1.0)))),
    )
    check(
        "supertrend flips at least once on random data",
        int(np.sum(np.abs(np.diff(direction[valid])) > 0)) > 0,
    )

    # A strong trend should hold one direction
    trend_c = list(np.linspace(100, 160, 120))
    trend_h = [x + 0.5 for x in trend_c]
    trend_l = [x - 0.5 for x in trend_c]
    t_line, t_dir = supertrend(trend_h, trend_l, trend_c, 21, 0.618)
    tail = t_dir[~np.isnan(t_dir)][-30:]
    check("supertrend stays long through a clean uptrend", bool(np.all(tail == -1)))

    # ADX bounds
    adx_v = adx(hn, ln, cn, 14, 14)
    fin = adx_v[~np.isnan(adx_v)]
    check("adx stays within 0..100", bool(np.all((fin >= 0) & (fin <= 100))), f"{fin.size} values")
    t_adx = adx(trend_h, trend_l, trend_c, 14, 14)
    t_fin = t_adx[~np.isnan(t_adx)]
    check(
        "adx is high on a clean trend",
        bool(t_fin.size and t_fin[-1] > 40),
        f"last {t_fin[-1]:.1f}" if t_fin.size else "no values",
    )

    # VWAP invariants
    vwap = session_vwap(hn, ln, cn, np.array(v))
    check(
        "vwap stays inside the session range",
        bool(np.nanmin(vwap) >= min(l) - 1e-9 and np.nanmax(vwap) <= max(h) + 1e-9),
    )
    # First bar VWAP equals that bar's typical price
    typical0 = (h[0] + l[0] + c[0]) / 3.0
    check("vwap of the first bar is its typical price", abs(vwap[0] - typical0) < 1e-9)
    # VWAP resets between sessions
    two_day = session_vwap(
        np.array(h[:20] + h[:20]),
        np.array(l[:20] + l[:20]),
        np.array(c[:20] + c[:20]),
        np.array(v[:20] + v[:20]),
        [1] * 20 + [2] * 20,
    )
    check("vwap resets on a new session", abs(two_day[0] - two_day[20]) < 1e-9)

    # Cross detection
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([3.0, 3.0, 2.5, 2.0])
    check("crossed_above fires on the crossing bar", crossed_above(a, b, 2))
    check("crossed_above does not fire while already above", not crossed_above(a, b, 3))

    # Resampling: 5 x 1-minute candles become one, OHLCV preserved
    day = session_open("NSE_EQ", __import__("datetime").date(2026, 9, 25)).date()
    one_min = _series(o, h, l, c, v, day)
    five = resample(one_min, 5, "NSE_EQ")
    check(
        "resample(5m) bucket count is right",
        len(five) == (len(one_min) + 4) // 5,
        f"{len(one_min)} 1m -> {len(five)} 5m",
    )
    first_bucket = five.candles[0]
    check(
        "resampled candle aggregates OHLCV correctly",
        first_bucket.open == o[0]
        and abs(first_bucket.high - max(h[:5])) < 1e-9
        and abs(first_bucket.low - min(l[:5])) < 1e-9
        and first_bucket.close == c[4]
        and abs(first_bucket.volume - sum(v[:5])) < 1e-9,
    )
    check(
        "resampled buckets are anchored to 09:15",
        first_bucket.ts.hour == 9 and first_bucket.ts.minute == 15,
        str(first_bucket.ts.time()),
    )

    # Forming-candle guard
    closed, forming = drop_forming(five, 5, five.candles[-1].ts + timedelta(minutes=2))
    check(
        "drop_forming removes the in-progress candle",
        forming is not None and len(closed) == len(five) - 1,
    )
    closed2, forming2 = drop_forming(five, 5, five.candles[-1].ts + timedelta(minutes=6))
    check("drop_forming keeps a completed candle", forming2 is None and len(closed2) == len(five))

    # Tick rounding
    check("round_to_tick snaps to 0.05", abs(round_to_tick(101.4267, 0.05) - 101.425) < 1e-9
          or abs(round_to_tick(101.4267, 0.05) - 101.45) < 1e-9)
    check("round_to_tick(100.02, 0.05) == 100.0", abs(round_to_tick(100.02, 0.05) - 100.0) < 1e-9)
    check("round_to_tick(100.04, 0.05) == 100.05", abs(round_to_tick(100.04, 0.05) - 100.05) < 1e-9)
    check("round_to_tick handles a 5.00 tick", abs(round_to_tick(152_347.0, 5.0) - 152_345.0) < 1e-9)

    # 3% stop maths: a 3% loss on capital deployed is a 3% adverse price move
    entry, qty = 250.0, 40
    stop = round_to_tick(entry * (1 - 3.0 / 100.0), 0.05)
    loss = (entry - stop) * qty
    capital = entry * qty
    check(
        "3% stop risks ~3% of capital deployed",
        abs(loss / capital - 0.03) < 1e-3,
        f"stop {stop}, risk {loss:.2f} on capital {capital:.2f} = {loss / capital * 100:.3f}%",
    )

    # Strategy wiring: conditions agree with the raw series
    cfg = StrategyConfig()
    ind = Indicators(one_min, cfg)
    sig = evaluate_entry(ind, cfg, ltp=float(one_min.close[-1]), require_adx=True)
    snap = sig.snapshot
    expected_vwap_flag = snap.vwap is not None and float(one_min.close[-1]) > snap.vwap
    check(
        "entry check price_above_vwap matches the snapshot",
        sig.checks.get("price_above_vwap") == expected_vwap_flag,
    )
    expected_rsi_flag = (
        snap.rsi is not None and snap.rsi_signal_entry is not None and snap.rsi > snap.rsi_signal_entry
    )
    check(
        "entry check rsi_above_signal matches the snapshot",
        sig.checks.get("rsi_above_signal") == expected_rsi_flag,
    )
    check(
        "entry check price_above_supertrend matches direction",
        sig.checks.get("price_above_supertrend") == (snap.supertrend_direction == -1),
    )
    check("entry gate reports every sub-condition", len(sig.checks) == 4, str(list(sig.checks)))
    check(
        "ready only when every check passes",
        sig.ready == all(sig.checks.values()),
    )

    # Warmup refusal
    short = CandleSeries(one_min.candles[:10])
    short_sig = evaluate_entry(Indicators(short, cfg), cfg, ltp=100.0)
    check("entry refuses without enough history", not short_sig.ready)

    # Exit evaluation returns a reason or None, consistent with the snapshot
    reason, exit_snap, _notes = evaluate_exit(ind, cfg)
    rsi_below = (
        exit_snap.rsi is not None
        and exit_snap.rsi_signal_exit is not None
        and exit_snap.rsi < exit_snap.rsi_signal_exit
    )
    st_down = exit_snap.supertrend_direction == 1
    check(
        "exit fires exactly when an exit condition holds",
        (reason is not None) == (rsi_below or st_down),
        f"reason={reason.value if reason else None} rsi_below={rsi_below} st_down={st_down}",
    )

    # Warmup bar count is self-consistent
    check(
        "warmup_bars covers the RSI->EMA chain",
        cfg.warmup_bars() >= cfg.rsi_period + cfg.rsi_signal_entry_period,
        f"warmup {cfg.warmup_bars()}",
    )

    results.extend(_chart_and_timeframe_checks(c, h, l))
    return results


def _chart_and_timeframe_checks(c: list, h: list, l: list) -> list[tuple[str, bool, str]]:
    """Timeframes, ZEMA, the stepped Supertrend, Heikin Ashi, Renko and basket weights."""
    from datetime import date

    from .baskets import unit_weights
    from .chart_types import heikin_ashi, renko
    from .data_source import Bar
    from .timeframes import TIMEFRAMES

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    codes = [code for code, _, _ in TIMEFRAMES]
    check("timeframes are 1m 3m 5m 9m 15m 30m 1h 2h 1D 1W 1M",
          codes == ["1m", "3m", "5m", "9m", "15m", "30m", "1h", "2h", "1D", "1W", "1M"], " ".join(codes))

    # ZEMA against the naive reference
    for period in (50, 200):
        mine = zema(c, period)
        theirs = np.array(ref_zema(c, period))
        both = ~(np.isnan(mine) | np.isnan(theirs))
        diff = float(np.max(np.abs(mine[both] - theirs[both]))) if both.any() else float("inf")
        first = int(np.flatnonzero(~np.isnan(mine))[0])
        check(f"zema(period={period}) matches reference", diff < 1e-9 and first == (period - 1) // 2 + period - 1,
              f"max diff {diff:.2e}, first value at bar {first}")
    flat = [42.0] * 300
    check("zema of a constant series is constant", abs(zema(flat, 50)[-1] - 42.0) < 1e-12)

    # Supertrend one bar at a time is the same recursion as the whole series
    line, direction = supertrend(h, l, c, 10, 3.0)
    states = supertrend_states(h, l, c, 10, 3.0)
    lines = np.array([s.line for s in states])
    dirs = np.array([s.direction for s in states])
    same = np.array_equal(np.isnan(lines), np.isnan(line)) and np.allclose(
        lines[~np.isnan(lines)], line[~np.isnan(line)], atol=1e-9)
    check("supertrend stepped bar by bar matches the series", same and np.array_equal(
        dirs[~np.isnan(dirs)], direction[~np.isnan(direction)]))
    stepped = supertrend_step(states[-2], h[-1], l[-1], c[-1], 10, 3.0)
    check("supertrend_step from the previous state gives the last value",
          abs(stepped.line - line[-1]) < 1e-9 and stepped.direction == direction[-1])

    # Long timeframes: day, week and month bars from 1-minute candles
    one_min = _days_series(date(2026, 8, 3), 25)   # Mon 3 Aug to Fri 4 Sep 2026
    days = resample(one_min, DAY, "NSE_EQ")
    weeks = resample(one_min, WEEK, "NSE_EQ")
    months = resample(one_min, MONTH, "NSE_EQ")
    first_day = [x for x in one_min.candles if x.ts.date() == date(2026, 8, 3)]
    d0 = days.candles[0]
    check("1D bars: one per session, OHLC of the session",
          len(days) == 25 and d0.open == first_day[0].open and d0.close == first_day[-1].close
          and abs(d0.high - max(x.high for x in first_day)) < 1e-9
          and abs(d0.low - min(x.low for x in first_day)) < 1e-9
          and abs(d0.volume - sum(x.volume for x in first_day)) < 1e-6,
          f"{len(days)} day bars")
    check("1W bars start on Monday and span Monday to Friday",
          len(weeks) == 5 and all(w.ts.weekday() == 0 for w in weeks.candles)
          and weeks.candles[0].close == days.candles[4].close, f"{len(weeks)} week bars")
    check("1M bars start on the 1st", [m.ts.day for m in months.candles] == [1, 1]
          and months.candles[1].ts.month == 9, f"{[m.ts.date().isoformat() for m in months.candles]}")
    weekly_from_daily = resample(days, WEEK, "NSE_EQ")
    check("week bars are the same from day bars as from minutes",
          [(w.ts, round(w.high, 6), round(w.low, 6), w.close) for w in weekly_from_daily.candles]
          == [(w.ts, round(w.high, 6), round(w.low, 6), w.close) for w in weeks.candles])
    two_h = resample(one_min, 120, "NSE_EQ")
    starts = sorted({x.ts.strftime("%H:%M") for x in two_h.candles})
    check("2h bars at 09:15, 11:15, 13:15 and the 15:15 remainder", starts == ["09:15", "11:15", "13:15", "15:15"],
          ", ".join(starts))
    nine = resample(one_min, 9, "NSE_EQ")
    check("9m bars: 42 a session, anchored at 09:15", len([x for x in nine.candles if x.ts.date() == date(2026, 8, 3)]) == 42
          and nine.candles[1].ts.strftime("%H:%M") == "09:24")

    # When a bar closes
    t = lambda d, hh, mm: session_open("NSE_EQ", d).replace(hour=hh, minute=mm)  # noqa: E731
    oct1 = date(2026, 10, 1)
    check("bar_end: 5m, the clipped 2h and 9m bars, day, week, month",
          bar_end(t(oct1, 10, 0), 5) == t(oct1, 10, 5)
          and bar_end(t(oct1, 15, 15), 120) == session_close("NSE_EQ", oct1)
          and bar_end(t(oct1, 15, 24), 9) == session_close("NSE_EQ", oct1)
          and bar_end(t(oct1, 9, 15), DAY) == session_close("NSE_EQ", oct1)
          and bar_end(t(date(2026, 9, 28), 9, 15), WEEK) == session_close("NSE_EQ", date(2026, 10, 2))
          and bar_end(t(date(2026, 10, 1), 9, 15), MONTH) == session_close("NSE_EQ", date(2026, 10, 30)))
    today_bar = CandleSeries([Candle(ts=t(oct1, 9, 15), open=1, high=1, low=1, close=1, volume=0)])
    _c, forming = drop_forming(today_bar, DAY, t(oct1, 12, 0))
    _c2, forming2 = drop_forming(today_bar, DAY, t(oct1, 15, 31))
    check("a day bar is forming until the close", forming is not None and forming2 is None)

    # Heikin Ashi
    bars = [Bar(time=60 * i, open=o, high=hh, low=ll, close=cc, volume=1.0)
            for i, (o, hh, ll, cc) in enumerate(zip(c[:-1], h[1:], l[1:], c[1:]))]
    bars = [Bar(time=b.time, open=b.open, high=max(b.high, b.open, b.close), low=min(b.low, b.open, b.close),
                close=b.close, volume=1.0) for b in bars]
    ha = heikin_ashi(bars)
    ok = abs(ha[0].open - (bars[0].open + bars[0].close) / 2) < 1e-6
    for i in range(1, len(ha)):
        b = bars[i]
        ok &= abs(ha[i].close - (b.open + b.high + b.low + b.close) / 4) < 1e-3
        ok &= abs(ha[i].open - (ha[i - 1].open + ha[i - 1].close) / 2) < 1e-3
        ok &= ha[i].high >= max(ha[i].open, ha[i].close) - 1e-9 and ha[i].low <= min(ha[i].open, ha[i].close) + 1e-9
    check("heikin ashi: averaged close, carried open, wicks contain the body", ok and len(ha) == len(bars))

    # Renko
    box = 2.0
    bricks = renko(bars, box)
    sizes_ok = all(abs(abs(b.close - b.open) - box) < 1e-6 for b in bricks)
    links_ok = all(abs(cur.open - prev.close) < 1e-6 or abs(cur.open - prev.open) < 1e-6
                   for prev, cur in zip(bricks, bricks[1:]))
    turns_ok = all((cur.close > cur.open) == (prev.close > prev.open) or abs(cur.open - prev.open) < 1e-6
                   for prev, cur in zip(bricks, bricks[1:]))
    times_ok = all(b2.time > b1.time for b1, b2 in zip(bricks, bricks[1:]))
    check("renko: bricks of one box, continuing or turning on two", bool(bricks) and sizes_ok and links_ok
          and turns_ok and times_ok, f"{len(bricks)} bricks")

    # Basket weights for the combined premium chart
    check("basket premium weights: equal lots chart as plain sum or difference",
          unit_weights([2, 2]) == [1.0, 1.0] and unit_weights([1, 2]) == [1.0, 2.0]
          and unit_weights([3, 6, 9]) == [1.0, 2.0, 3.0] and unit_weights([1.5, 3]) == [1.5, 3])
    return results


def main() -> int:
    results = run_checks()
    width = max(len(name) for name, _, _ in results) + 2
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        line = f"  [{mark}] {name.ljust(width)}"
        if detail:
            line += f"  {detail}"
        print(line)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0
