"""Entry and exit rules.

Entry (long only), evaluated on the last CLOSED candle of the chosen timeframe:
  0. LTP > session VWAP
  1. RSI(21) above EMA(RSI(21), 21)
  2. price above Supertrend(21, 0.618)
  3. options only: ADX(14) > 20

Exit: the Strategy tab's exit conditions (rules.py) - rows of indicator, comparison
and indicator or number, joined by AND / OR, each checked on candle close or on the
live price. The default rows are the original two:
  a. RSI(21) below EMA(RSI(21), 9)        on candle close
  b. close below Supertrend(21, 0.618)    on candle close
plus a hard stop, an optional target and trailing stop, all handled by the engine on
LTP between candles.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from .candles import CandleSeries
from .config import StrategyConfig
from .indicators import (
    adx as adx_ind,
    crossed_above,
    crossed_below,
    ema,
    ema_of,
    rsi as rsi_ind,
    session_vwap,
    supertrend as supertrend_ind,
)
from .models import Direction, ExitReason, SignalResult, Snapshot
from .rules import RulesOutcome, effective_rules
from .rules import evaluate as evaluate_rules


def _f(value) -> float | None:
    if value is None:
        return None
    v = float(value)
    return None if np.isnan(v) else v


class Indicators:
    """All series for one instrument on one timeframe, computed once per poll."""

    __slots__ = (
        "series",
        "cfg",
        "vwap",
        "rsi",
        "rsi_entry",
        "rsi_exit",
        "st_line",
        "st_dir",
        "price_ema",
        "adx",
        "n",
    )

    def __init__(self, series: CandleSeries, cfg: StrategyConfig):
        self.series = series
        self.cfg = cfg
        self.n = len(series)

        if self.n == 0:
            empty = np.full(0, np.nan)
            self.vwap = self.rsi = self.rsi_entry = self.rsi_exit = empty
            self.st_line = self.st_dir = self.price_ema = self.adx = empty
            return

        h, l, c, v = series.high, series.low, series.close, series.volume
        self.vwap = session_vwap(h, l, c, v, series.session_ids)
        self.rsi = rsi_ind(c, cfg.rsi_period)
        self.rsi_entry = ema_of(self.rsi, cfg.rsi_signal_entry_period)
        self.rsi_exit = ema_of(self.rsi, cfg.rsi_signal_exit_period)
        self.st_line, self.st_dir = supertrend_ind(
            h, l, c, cfg.supertrend_period, cfg.supertrend_factor
        )
        self.price_ema = ema(c, cfg.price_ema_period)
        self.adx = adx_ind(h, l, c, cfg.adx_period, cfg.adx_period)

    def snapshot(self, ltp: float | None = None) -> Snapshot:
        if self.n == 0:
            return Snapshot(bars=0, ltp=ltp)
        i = self.n - 1
        direction = _f(self.st_dir[i])
        return Snapshot(
            candle_ts=self.series.candles[i].ts,
            ltp=ltp if ltp is not None else _f(self.series.close[i]),
            close=_f(self.series.close[i]),
            vwap=_f(self.vwap[i]),
            rsi=_f(self.rsi[i]),
            rsi_signal_entry=_f(self.rsi_entry[i]),
            rsi_signal_exit=_f(self.rsi_exit[i]),
            supertrend=_f(self.st_line[i]),
            supertrend_direction=int(direction) if direction is not None else None,
            price_ema=_f(self.price_ema[i]),
            adx=_f(self.adx[i]),
            bars=self.n,
        )


def evaluate_entry(
    ind: Indicators,
    cfg: StrategyConfig,
    *,
    ltp: float | None,
    require_adx: bool = False,
    adx_min: float | None = None,
    direction: Direction = Direction.LONG,
) -> SignalResult:
    """Entry gate for either direction.

    A short is the exact mirror of a long: price below session VWAP instead of above, RSI
    below its signal line, price below Supertrend. ADX is directionless, so that
    check is unchanged. Every sub-condition is reported so the approval card can show
    exactly why the engine wants in.
    """
    snap = ind.snapshot(ltp)
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    why: dict[str, str] = {}      # the same reasons, by the check they explain
    short = direction is Direction.SHORT

    def fail(check: str, text: str) -> None:
        reasons.append(text)
        why[check] = text

    warmup = cfg.warmup_bars()
    if ind.n < warmup:
        text = f"need {warmup} closed candles, have {ind.n}"
        return SignalResult(
            ready=False,
            checks={"enough_history": False},
            reasons=[text],
            snapshot=snap,
            why={"enough_history": text},
        )

    i = ind.n - 1
    price = ltp if ltp is not None else float(ind.series.close[i])

    side_word = "below" if short else "above"

    # 0. current price on the right side of the session VWAP (the centerline, never a band)
    vwap = snap.vwap
    ok_vwap = vwap is not None and (price < vwap if short else price > vwap)
    checks[f"price_{side_word}_vwap"] = ok_vwap
    if not ok_vwap:
        fail(
            f"price_{side_word}_vwap",
            f"price {price:.2f} is not {side_word} VWAP {vwap:.2f}" if vwap is not None
            else "VWAP unavailable",
        )

    # 1. RSI on the right side of its 21-EMA signal line
    rsi_v, sig_v = snap.rsi, snap.rsi_signal_entry
    if cfg.entry_condition_mode == "cross":
        ok_rsi = (
            crossed_below(ind.rsi, ind.rsi_entry, i)
            if short
            else crossed_above(ind.rsi, ind.rsi_entry, i)
        )
        label = f"crossed {side_word}"
    else:
        ok_rsi = (
            rsi_v is not None
            and sig_v is not None
            and (rsi_v < sig_v if short else rsi_v > sig_v)
        )
        label = side_word
    checks[f"rsi_{side_word}_signal"] = ok_rsi
    if not ok_rsi:
        if rsi_v is None or sig_v is None:
            fail(f"rsi_{side_word}_signal", "RSI or its signal line is not available yet")
        else:
            fail(
                f"rsi_{side_word}_signal",
                f"RSI({cfg.rsi_period}) {rsi_v:.2f} not {label} "
                f"EMA(RSI,{cfg.rsi_signal_entry_period}) {sig_v:.2f}",
            )

    # 2. price on the right side of supertrend (+1 = downtrend, -1 = uptrend)
    st_v, st_dir = snap.supertrend, snap.supertrend_direction
    wanted_dir = 1 if short else -1
    if cfg.entry_condition_mode == "cross":
        close_arr = ind.series.close
        fresh_flip = st_dir == wanted_dir and i >= 1 and ind.st_dir[i - 1] == -wanted_dir
        crossed = (
            crossed_below(close_arr, ind.st_line, i)
            if short
            else crossed_above(close_arr, ind.st_line, i)
        )
        ok_st = crossed or fresh_flip
    else:
        ok_st = st_dir == wanted_dir
    checks[f"price_{side_word}_supertrend"] = bool(ok_st)
    if not ok_st:
        if st_v is None:
            fail(f"price_{side_word}_supertrend", "Supertrend not available yet")
        else:
            fail(
                f"price_{side_word}_supertrend",
                f"price {float(ind.series.close[i]):.2f} not {side_word} "
                f"Supertrend({cfg.supertrend_period},{cfg.supertrend_factor}) {st_v:.2f}",
            )

    # 3. ADX filter (options strategy)
    if require_adx:
        threshold = adx_min if adx_min is not None else cfg.adx_min
        if threshold is None:
            checks["adx_above_min"] = True
        else:
            adx_v = snap.adx
            ok_adx = adx_v is not None and adx_v > threshold
            checks["adx_above_min"] = ok_adx
            if not ok_adx:
                fail(
                    "adx_above_min",
                    f"ADX({cfg.adx_period}) {adx_v:.2f} not above {threshold:.2f}"
                    if adx_v is not None
                    else "ADX not available yet",
                )

    ready = all(checks.values())
    if ready:
        reasons.append("all entry conditions satisfied")
    return SignalResult(ready=ready, checks=checks, reasons=reasons, snapshot=snap, why=why)


def exit_outcome(
    closed: CandleSeries,
    cfg: StrategyConfig,
    direction: Direction = Direction.LONG,
    *,
    live: CandleSeries | None = None,
    entry_time: datetime | None = None,
    timeframe_minutes: int | None = None,
    segment: str = "NSE_EQ",
) -> RulesOutcome:
    """The exit conditions checked against these candles, mirrored for a short.

    `closed` must hold closed candles only. Rows set to "live" read `live`, which
    adds the forming candle priced at LTP (rules.live_series); without it they read
    the last closed candle. `entry_time` makes candle-close rows ignore candles that
    had already closed when the position was opened.
    """
    return evaluate_rules(
        effective_rules(cfg),
        closed=closed,
        live=live,
        short=direction is Direction.SHORT,
        entry_time=entry_time,
        timeframe_minutes=timeframe_minutes or cfg.timeframe_minutes,
        segment=segment,
    )


def evaluate_exit(
    ind: Indicators,
    cfg: StrategyConfig,
    direction: Direction = Direction.LONG,
) -> tuple[ExitReason | None, Snapshot, list[str]]:
    """Indicator-based exits on the last closed candle, mirrored for shorts.

    With the default rows a long exits when RSI loses its 9-EMA or price loses the
    Supertrend; a short exits when RSI reclaims the 9-EMA or price reclaims the
    Supertrend. Stop-loss, target and trailing stop are price triggers handled by
    the engine so they can fire between candles.
    """
    snap = ind.snapshot()
    if ind.n == 0:
        return None, snap, ["no candles"]
    outcome = exit_outcome(ind.series, cfg, direction)
    return (ExitReason.EXIT_RULE if outcome.fired else None), snap, [outcome.text]
