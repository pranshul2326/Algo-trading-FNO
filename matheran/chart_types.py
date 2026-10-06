"""Chart types other than plain candles: Heikin Ashi and Renko.

Both are drawn from the same OHLCV bars every provider returns, so they work for any
data source and any timeframe.

* Heikin Ashi smooths each candle with the one before it:

      close = (open + high + low + close) / 4
      open  = (previous HA open + previous HA close) / 2     (first: (open + close) / 2)
      high  = max(high, HA open, HA close)
      low   = min(low, HA open, HA close)

  One HA candle per real candle, at the same time, so the indicators on a Heikin
  Ashi chart are still computed on the real prices: the same numbers the engine
  trades on.

* Renko draws a brick each time the close moves a whole box from the last brick, and
  needs a move of two boxes to turn round. Bricks carry no time of their own; each
  takes the time of the candle that completed it (plus a second per extra brick, so
  the times stay unique). Indicators on a Renko chart are computed on the bricks,
  since nothing else lines up with them.
"""

from __future__ import annotations

import numpy as np

from .data_source import Bar
from .indicators import atr
from .models import round_to_tick

CHART_TYPES = ("candles", "heikin_ashi", "renko")


def heikin_ashi(bars: list[Bar]) -> list[Bar]:
    out: list[Bar] = []
    ha_open = ha_close = None
    for b in bars:
        close = (b.open + b.high + b.low + b.close) / 4.0
        open_ = (b.open + b.close) / 2.0 if ha_open is None else (ha_open + ha_close) / 2.0
        out.append(Bar(
            time=b.time,
            open=round(open_, 4),
            high=round(max(b.high, open_, close), 4),
            low=round(min(b.low, open_, close), 4),
            close=round(close, 4),
            volume=b.volume,
            oi=b.oi,
        ))
        ha_open, ha_close = open_, close
    return out


def atr_box(bars: list[Bar], period: int = 14, tick: float = 0.05) -> float:
    """A box size from the latest ATR, on the tick grid, as TradingView's ATR setting does."""
    if not bars:
        return max(tick, 0.05)
    high = np.array([b.high for b in bars], dtype=float)
    low = np.array([b.low for b in bars], dtype=float)
    close = np.array([b.close for b in bars], dtype=float)
    values = atr(high, low, close, max(1, int(period)))
    finite = values[~np.isnan(values)]
    size = float(finite[-1]) if finite.size else abs(float(close[-1])) * 0.005
    return max(tick, round_to_tick(size, tick) or tick)


def renko(bars: list[Bar], box: float) -> list[Bar]:
    """Traditional close-based Renko: continue on a one-box move, reverse on two."""
    if not bars or not box or box <= 0:
        return []
    out: list[Bar] = []
    base = np.floor(bars[0].close / box) * box
    hi = lo = float(base)
    direction = 0          # +1 last brick up, -1 down, 0 none yet
    pending_volume = 0.0
    last_time = None

    def emit(t: int, o: float, c: float, volume: float) -> None:
        nonlocal last_time
        t = int(t) if last_time is None else max(int(t), last_time + 1)
        last_time = t
        out.append(Bar(time=t, open=round(o, 4), high=round(max(o, c), 4),
                       low=round(min(o, c), 4), close=round(c, 4), volume=volume))

    for b in bars:
        c = b.close
        pending_volume += b.volume
        made: list[tuple[float, float]] = []
        while True:
            if direction >= 0 and c >= hi + box:          # up: continuation or first
                made.append((hi, hi + box))
                lo, hi, direction = hi, hi + box, 1
            elif direction <= 0 and c <= lo - box:        # down: continuation or first
                made.append((lo, lo - box))
                hi, lo, direction = lo, lo - box, -1
            elif direction == 1 and c <= lo - box:        # reversal down: two boxes
                made.append((lo, lo - box))
                hi, lo, direction = lo, lo - box, -1
            elif direction == -1 and c >= hi + box:       # reversal up: two boxes
                made.append((hi, hi + box))
                lo, hi, direction = hi, hi + box, 1
            else:
                break
        if made:
            share = pending_volume / len(made)
            for o, cl in made:
                emit(b.time, o, cl, share)
            pending_volume = 0.0
    return out
