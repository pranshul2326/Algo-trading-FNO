"""Combined premium of a basket's legs, the way the TradingView combo script draws it.

This follows the Pine Script "Multi-Strike Option Combo + Call/Put Charts" (see
trading_view_script.md), so the combo candles, the call and put baskets and their
indicators read the same numbers here as on a TradingView chart.

Legs are weighted by lots, as the script weights them, with the lots reduced by their
common divisor so the charts read in premium points (never price x lot size): legs in
equal lots chart as the plain sum or difference of their prices.

  * one leg               -> its price
  * two legs, same side   -> their sum; opposite sides -> their difference, unsigned
  * three legs or more    -> signed net: +w x price bought, -w x price sold

A combo's open and close are exact, but its high and low have to be inferred. The
script's "Bar range" input picks how:

  * spot  - value the combo with the underlying at its bar high and again at its bar
            low: every call at its high while every put is at its low, and the
            reverse. The script's recommended default.
  * body  - no wicks, open to close only.
  * wicks - add up each leg's own extreme, as if they all peaked on the same tick.
            Overstates the range of a straddle several times over.

The call and put baskets are the same arithmetic over the CE or the PE legs alone,
shown as absolute values (what the spread costs) or signed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np

from .baskets import unit_weights
from .data_source import Bar
from .indicators import ema, session_vwap, session_vwap_bands, supertrend
from .timeutil import IST

RANGE_MODES = ("spot", "body", "wicks")


@dataclass(slots=True)
class ComboLeg:
    symbol: str
    label: str
    sign: int                        # +1 bought, -1 sold
    lots: float                      # the weight, in lots
    option_type: str | None = None   # CE, PE, or None for a future / stock leg
    lot_size: int = 1
    strike: float | None = None
    expiry: str | None = None
    entry: float | None = None       # average entry, while the leg is open
    error: str = ""

    @property
    def is_call(self) -> bool:
        # A future or a stock rises with the underlying, the way a call does.
        return self.option_type != "PE"


@dataclass(slots=True)
class Aligned:
    """Every leg on one timeline: arrays shaped (legs, bars)."""

    times: list[int]
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray


def align(leg_bars: list[list[Bar]]) -> Aligned:
    """Put the legs on the union of their bar times.

    A leg that did not trade in a bar is carried as a flat bar at its previous close
    with no volume, which is what "nothing traded" means. Before its first bar a leg
    is absent (NaN), the way a request.security() series is na before its data starts.
    """
    times = sorted({b.time for bars in leg_bars for b in bars})
    shape = (len(leg_bars), len(times))
    o = np.full(shape, np.nan)
    h = np.full(shape, np.nan)
    l = np.full(shape, np.nan)
    c = np.full(shape, np.nan)
    v = np.zeros(shape)
    index = {t: i for i, t in enumerate(times)}
    for j, bars in enumerate(leg_bars):
        for b in bars:
            i = index[b.time]
            o[j, i], h[j, i], l[j, i], c[j, i], v[j, i] = b.open, b.high, b.low, b.close, b.volume
        last = math.nan
        for i in range(len(times)):
            if math.isnan(c[j, i]):
                if not math.isnan(last):
                    o[j, i] = h[j, i] = l[j, i] = c[j, i] = last
            else:
                last = c[j, i]
    return Aligned(times, o, h, l, c, v)


def _active(legs: list[ComboLeg], al: Aligned, i: int, members=None) -> list[int]:
    pool = range(len(legs)) if members is None else members
    return [j for j in pool if legs[j].lots > 0 and not math.isnan(al.c[j, i])]


def combo_bars(legs: list[ComboLeg], al: Aligned, mode: str = "spot") -> list[Bar]:
    """The combo candle per bar: the script's combo open/high/low/close."""
    out: list[Bar] = []
    for i, t in enumerate(al.times):
        act = _active(legs, al, i)
        if not act:
            continue
        q = {j: legs[j].lots for j in act}
        s = {j: legs[j].sign for j in act}
        o = {j: al.o[j, i] for j in act}
        h = {j: al.h[j, i] for j in act}
        lo = {j: al.l[j, i] for j in act}
        c = {j: al.c[j, i] for j in act}

        if len(act) == 1:
            j = act[0]
            open_, close = q[j] * o[j], q[j] * c[j]
            wick_hi, wick_lo = q[j] * h[j], q[j] * lo[j]
        elif len(act) == 2:
            a, b = act
            a_o, a_h, a_l, a_c = q[a] * o[a], q[a] * h[a], q[a] * lo[a], q[a] * c[a]
            b_o, b_h, b_l, b_c = q[b] * o[b], q[b] * h[b], q[b] * lo[b], q[b] * c[b]
            if s[a] != s[b]:
                # A spread: the difference between the legs, never negative.
                open_, close = abs(a_o - b_o), abs(a_c - b_c)
                wick_hi = max(abs(a_h - b_l), abs(b_h - a_l))
                wick_lo = min(abs(a_l - b_h), abs(b_l - a_h))
            else:
                open_, close = a_o + b_o, a_c + b_c
                wick_hi, wick_lo = a_h + b_h, a_l + b_l
            wick_hi = max(wick_hi, open_, close)
            wick_lo = min(wick_lo, open_, close)
        else:
            open_ = sum(s[j] * q[j] * o[j] for j in act)
            close = sum(s[j] * q[j] * c[j] for j in act)
            raw_hi = sum(q[j] * h[j] if s[j] > 0 else -q[j] * lo[j] for j in act)
            raw_lo = sum(q[j] * lo[j] if s[j] > 0 else -q[j] * h[j] for j in act)
            wick_hi = max(raw_hi, open_, close)
            wick_lo = min(raw_lo, open_, close)

        if mode == "wicks":
            high, low = wick_hi, wick_lo
        elif mode == "body":
            high, low = max(open_, close), min(open_, close)
        else:
            # Spot linked: the whole combo valued at the underlying's bar high (calls
            # high, puts low) and at its bar low (the reverse).
            at_hi = sum(s[j] * q[j] * (h[j] if legs[j].is_call else lo[j]) for j in act)
            at_lo = sum(s[j] * q[j] * (lo[j] if legs[j].is_call else h[j]) for j in act)
            if len(act) <= 2:
                # One- and two-leg combos are shown unsigned, so their ends are too.
                at_hi, at_lo = abs(at_hi), abs(at_lo)
            high = max(at_hi, at_lo, open_, close)
            low = min(at_hi, at_lo, open_, close)

        out.append(_bar(t, open_, high, low, close, sum(al.v[j, i] for j in act)))
    return out


def _bar(t: int, o: float, h: float, l: float, c: float, v: float) -> Bar:
    return Bar(time=int(t), open=round(float(o), 4), high=round(float(h), 4),
               low=round(float(l), 4), close=round(float(c), 4), volume=float(v))


def side_bars(
    legs: list[ComboLeg],
    al: Aligned,
    option_type: str,
    mode: str = "spot",
    absolute: bool = True,
) -> list[Bar] | None:
    """The call-only (CE) or put-only (PE) basket, or None when there is no such leg."""
    members = [j for j, leg in enumerate(legs) if leg.option_type == option_type]
    if not members:
        return None
    out: list[Bar] = []
    for i, t in enumerate(al.times):
        act = _active(legs, al, i, members)
        if not act:
            continue
        net_o = net_c = net_h = net_l = end_a = end_b = 0.0
        for j in act:
            q, s = legs[j].lots, legs[j].sign
            o, h, lo, c = al.o[j, i], al.h[j, i], al.l[j, i], al.c[j, i]
            net_o += s * q * o
            net_c += s * q * c
            net_h += q * h if s > 0 else -q * lo
            net_l += q * lo if s > 0 else -q * h
            # Every leg of one type moves together: all at their highs at once, or
            # all at their lows.
            end_a += s * q * h
            end_b += s * q * lo
        if absolute:
            o0, c0 = abs(net_o), abs(net_c)
            h0, l0 = max(abs(net_h), abs(net_l)), min(abs(net_h), abs(net_l))
            sa, sb = abs(end_a), abs(end_b)
        else:
            o0, c0, h0, l0, sa, sb = net_o, net_c, net_h, net_l, end_a, end_b
        if mode == "wicks":
            high, low = max(h0, o0, c0), min(l0, o0, c0)
        elif mode == "body":
            high, low = max(o0, c0), min(o0, c0)
        else:
            high, low = max(sa, sb, o0, c0), min(sa, sb, o0, c0)
        out.append(_bar(t, o0, high, low, c0, sum(al.v[j, i] for j in act)))
    return out


def _points(times: list[int], values: np.ndarray) -> list[dict]:
    return [
        {"time": t, "value": round(float(x), 4)}
        for t, x in zip(times, values)
        if not math.isnan(float(x))
    ]


def combo_indicators(
    bars: list[Bar],
    *,
    ema1: int = 9,
    ema2: int = 21,
    st_factor: float = 3.0,
    st_atr: int = 10,
    vwap_mult: float = 2.0,
) -> dict[str, list[dict]]:
    """The script's VWAP, two EMAs and Supertrend, computed on the combo itself, plus
    the Advanced VWAP Bands (upper and lower only; "vwap" stays the centerline)."""
    if not bars:
        return {}
    times = [b.time for b in bars]
    high = np.array([b.high for b in bars], dtype=float)
    low = np.array([b.low for b in bars], dtype=float)
    close = np.array([b.close for b in bars], dtype=float)
    volume = np.array([b.volume for b in bars], dtype=float)
    sessions = [datetime.fromtimestamp(t, IST).date() for t in times]
    line, direction = supertrend(high, low, close, st_atr, st_factor)
    _center, upper, lower = session_vwap_bands(high, low, close, volume, sessions, vwap_mult)
    return {
        "vwap": _points(times, session_vwap(high, low, close, volume, sessions)),
        "vwap_bands": [
            {"time": t, "upper": round(float(u), 4), "lower": round(float(lo), 4)}
            for t, u, lo in zip(times, upper, lower)
            if not (math.isnan(float(u)) or math.isnan(float(lo)))
        ],
        "ema1": _points(times, ema(close, ema1)),
        "ema2": _points(times, ema(close, ema2)),
        "supertrend": [
            {"time": t, "value": round(float(x), 4), "trend": -1 if d == -1 else 1}
            for t, x, d in zip(times, line, direction)
            if not math.isnan(float(x))
        ],
    }


def _last_close(al: Aligned, j: int) -> float | None:
    row = al.c[j]
    finite = np.flatnonzero(~np.isnan(row))
    return float(row[finite[-1]]) if finite.size else None


def leg_table(legs: list[ComboLeg], al: Aligned) -> dict:
    """The script's info table: each leg, then CALLS, PUTS and TOTAL, in points and rupees."""
    rows = []
    for j, leg in enumerate(legs):
        ltp = _last_close(al, j) if len(al.times) else None
        ok = ltp is not None and leg.lots > 0
        pl = leg.sign * (ltp - leg.entry) * leg.lots if ok and leg.entry else None
        rows.append({
            "symbol": leg.symbol,
            "label": leg.label,
            "strike": leg.strike,
            "option_type": leg.option_type,
            "expiry": leg.expiry,
            "side": "BUY" if leg.sign > 0 else "SELL",
            "lots": leg.lots,
            "qty_text": ("+" if leg.sign > 0 else "-") + f"{leg.lots:g}",
            "quantity": round(leg.lots * leg.lot_size, 4),
            "lot_size": leg.lot_size,
            "entry": leg.entry,
            "ltp": round(ltp, 2) if ltp is not None else None,
            "pl_points": round(pl, 2) if pl is not None else None,
            "pl_rupees": round(pl * leg.lot_size, 2) if pl is not None else None,
            "has_data": ok,
            "error": leg.error,
        })

    def group(name: str, pick) -> dict:
        members = [(leg, row) for leg, row in zip(legs, rows) if pick(leg) and row["has_data"]]
        entered = [(leg, row) for leg, row in members if leg.entry]
        return {
            "name": name,
            "legs": len(members),
            "lots_net": round(sum(leg.sign * leg.lots for leg, _ in members), 4),
            "entry_points": round(sum(leg.sign * leg.entry * leg.lots for leg, _ in entered), 2)
            if entered else None,
            "entry_rupees": round(sum(leg.sign * leg.entry * leg.lots * leg.lot_size
                                      for leg, _ in entered), 2) if entered else None,
            "value_points": round(sum(leg.sign * leg.lots * row["ltp"] for leg, row in members), 2)
            if members else None,
            "value_rupees": round(sum(leg.sign * leg.lots * leg.lot_size * row["ltp"]
                                      for leg, row in members), 2) if members else None,
            "pl_points": round(sum(row["pl_points"] for _, row in entered), 2) if entered else None,
            "pl_rupees": round(sum(row["pl_rupees"] for _, row in entered), 2) if entered else None,
        }

    return {
        "legs": rows,
        "calls": group("CALLS", lambda leg: leg.option_type == "CE"),
        "puts": group("PUTS", lambda leg: leg.option_type == "PE"),
        "total": group("TOTAL", lambda leg: True),
    }


def build(
    legs: list[ComboLeg],
    leg_bars: list[list[Bar]],
    *,
    mode: str = "spot",
    absolute: bool = True,
    ema1: int = 9,
    ema2: int = 21,
    st_factor: float = 3.0,
    st_atr: int = 10,
    vwap_mult: float = 2.0,
) -> dict:
    """Combo, call basket, put basket, indicators and the leg table in one payload."""
    if mode not in RANGE_MODES:
        raise ValueError(f"bar range must be one of {', '.join(RANGE_MODES)}")
    al = align(leg_bars)
    # The charts are in premium points: lots reduced by their common divisor, so equal
    # lots plot as the plain sum or difference of the leg prices. The table keeps the
    # real lots, since its P/L is the position's.
    weights = unit_weights([leg.lots for leg in legs])
    chart_legs = [replace(leg, lots=w) for leg, w in zip(legs, weights)]
    combo = combo_bars(chart_legs, al, mode)
    calls = side_bars(chart_legs, al, "CE", mode, absolute)
    puts = side_bars(chart_legs, al, "PE", mode, absolute)
    return {
        "combo": {
            "bars": [b.as_dict() for b in combo],
            "indicators": combo_indicators(combo, ema1=ema1, ema2=ema2,
                                           st_factor=st_factor, st_atr=st_atr,
                                           vwap_mult=vwap_mult),
        },
        "call": {"bars": [b.as_dict() for b in calls]} if calls is not None else None,
        "put": {"bars": [b.as_dict() for b in puts]} if puts is not None else None,
        "table": leg_table(legs, al),
    }
