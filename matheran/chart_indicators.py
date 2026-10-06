"""Indicator series for the charts, derived from plain OHLCV bars.

This sits deliberately outside the data-source contract. Every provider returns
OHLCV and nothing more, so indicators are computed here from whatever came back.
Adding a broker therefore never means implementing indicators again.

The strategy's own indicators (VWAP, EMA, Supertrend, RSI and its signal lines, ADX)
use the same functions and the same periods from the same config, so what the chart
draws and what the engine acts on cannot drift apart. The single difference is that
charts include the bar still forming, while the engine only ever acts on closed bars.

Chart-only indicators carry parameters of their own, edited on the charts page:

  * ZEMA, the zero-lag EMA, twice (default 50 and 200);
  * a Supertrend on two timeframes, each with its own timeframe, ATR period and factor.
    A timeframe above the chart's is drawn the way it read live: on each chart bar,
    the higher-timeframe Supertrend of the bar in progress, built from the chart bars
    up to that one. It settles on the higher bar's own value at the chart bar that
    closes it, so nothing on a closed higher bar repaints.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from datetime import datetime

import numpy as np

from .candles import bar_end
from .config import StrategyConfig
from .data_source import Bar
from .indicators import (
    adx as adx_ind,
    ema,
    ema_of,
    rsi as rsi_ind,
    session_vwap,
    supertrend,
    supertrend_states,
    supertrend_step,
    zema,
)
from .timeframes import CODE_MINUTES, normalise
from .timeutil import IST


def _int(key: str, label: str, default: int, lo: int, hi: int) -> dict:
    return {"key": key, "label": label, "type": "int", "default": default, "min": lo, "max": hi}


def _float(key: str, label: str, default: float, lo: float, hi: float, step: float) -> dict:
    return {"key": key, "label": label, "type": "float", "default": default, "min": lo,
            "max": hi, "step": step}


def _tf(key: str, label: str, default: str) -> dict:
    # "chart" follows the pane's own timeframe.
    return {"key": key, "label": label, "type": "tf", "default": default}


# Everything the charts can draw. `pane` 0 is the price chart; 1 and 2 are the
# stacked sub-panes. `overlay` means it shares the price axis. `color` is the default
# line colour; an entry with `color_down` is drawn in two colours (up/down trend) and
# the charts page offers a picker for each. `params` are edited on the charts page.
CATALOG: tuple[dict, ...] = (
    {"id": "vwap", "label": "VWAP (session)", "pane": 0, "overlay": True, "color": "#f2cc60",
     "default": True},
    {"id": "ema_price", "label": "EMA(21) on price", "pane": 0, "overlay": True,
     "color": "#58a6ff", "default": True},
    {"id": "supertrend", "label": "Supertrend (21, 0.618)", "pane": 0, "overlay": True,
     "color": "#3fb950", "color_down": "#f85149", "default": True},
    {"id": "zema_fast", "label": "ZEMA (zero-lag EMA)", "pane": 0, "overlay": True,
     "color": "#ff9f43", "default": False, "params": (_int("period", "Period", 50, 2, 1000),)},
    {"id": "zema_slow", "label": "ZEMA (zero-lag EMA)", "pane": 0, "overlay": True,
     "color": "#c297ff", "default": False, "params": (_int("period", "Period", 200, 2, 1000),)},
    {"id": "st_tf1", "label": "Supertrend, timeframe 1", "pane": 0, "overlay": True,
     "color": "#26a69a", "color_down": "#ef5350", "default": False,
     "params": (_tf("tf", "Timeframe", "chart"), _int("period", "ATR period", 10, 1, 500),
                _float("factor", "Factor", 3.0, 0.01, 50.0, 0.1))},
    {"id": "st_tf2", "label": "Supertrend, timeframe 2", "pane": 0, "overlay": True,
     "color": "#29b6f6", "color_down": "#ffa726", "default": False,
     "params": (_tf("tf", "Timeframe", "15m"), _int("period", "ATR period", 10, 1, 500),
                _float("factor", "Factor", 3.0, 0.01, 50.0, 0.1))},
    {"id": "rsi", "label": "RSI(21)", "pane": 1, "overlay": False, "color": "#e6edf3",
     "default": True},
    {"id": "rsi_signal_entry", "label": "EMA(RSI, 21) — entry line", "pane": 1,
     "overlay": False, "color": "#f2cc60", "default": True},
    {"id": "rsi_signal_exit", "label": "EMA(RSI, 9) — exit line", "pane": 1,
     "overlay": False, "color": "#f85149", "default": True},
    {"id": "adx", "label": "ADX(14)", "pane": 2, "overlay": False, "color": "#bc8cff",
     "default": False},
)
CATALOG_IDS = {c["id"] for c in CATALOG}
DEFAULT_IDS = [c["id"] for c in CATALOG if c["default"]]
_BY_ID = {c["id"]: c for c in CATALOG}
TWO_TF_SUPERTRENDS = ("st_tf1", "st_tf2")
MAX_WARMUP = 1500


# ------------------------------------------------------------------- params
def _check(spec: dict, values: dict) -> dict:
    out: dict = {}
    for p in spec.get("params", ()):
        raw = values.get(p["key"])
        if raw is None or raw == "":
            continue
        where = f"{spec['label']} {p['label'].lower()}"
        if p["type"] == "tf":
            text = str(raw)
            if text != "chart":
                code = normalise(text)
                if code is None:
                    raise ValueError(f"{where}: unknown timeframe {text!r}")
                text = code
            out[p["key"]] = text
            continue
        try:
            num = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{where} must be a number, got {raw!r}") from None
        if not math.isfinite(num) or num < p["min"] or num > p["max"]:
            raise ValueError(f"{where} must be between {p['min']:g} and {p['max']:g}")
        if p["type"] == "int":
            if not num.is_integer():
                raise ValueError(f"{where} must be a whole number")
            num = int(num)
        out[p["key"]] = num
    return out


def parse_params(text: str | None) -> dict[str, dict]:
    """The candles endpoint's `params`: JSON {indicator id: {parameter: value}}."""
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except ValueError:
        raise ValueError("params must be a JSON object of indicator id -> parameters") from None
    if not isinstance(raw, dict):
        raise ValueError("params must be a JSON object of indicator id -> parameters")
    out: dict[str, dict] = {}
    for ind_id, values in raw.items():
        spec = _BY_ID.get(str(ind_id))
        if spec is None:
            raise ValueError(f"unknown indicator '{ind_id}' in params")
        if not spec.get("params"):
            continue
        if not isinstance(values, dict):
            raise ValueError(f"params for {ind_id} must be an object")
        out[str(ind_id)] = _check(spec, values)
    return out


def resolved(ind_id: str, params: dict | None) -> dict:
    """An indicator's parameters with defaults filled in."""
    spec = _BY_ID[ind_id]
    given = (params or {}).get(ind_id, {})
    return {p["key"]: given.get(p["key"], p["default"]) for p in spec.get("params", ())}


def warmup_bars(cfg: StrategyConfig, wanted: list[str], params: dict | None = None) -> int:
    """Bars to load before the first one shown, so the lines on screen have settled
    rather than just begun. EMA-type averages are taken as settled after about three
    periods."""
    need = 0
    for ind in wanted:
        if ind in ("zema_fast", "zema_slow"):
            p = int(resolved(ind, params)["period"])
            need = max(need, (p - 1) // 2 + 3 * p)
        elif ind == "ema_price":
            need = max(need, 3 * cfg.price_ema_period)
        elif ind in ("rsi", "rsi_signal_entry", "rsi_signal_exit"):
            need = max(need, cfg.rsi_period + 3 * max(cfg.rsi_signal_entry_period,
                                                      cfg.rsi_signal_exit_period))
        elif ind == "supertrend":
            need = max(need, 3 * cfg.supertrend_period)
        elif ind == "adx":
            need = max(need, 4 * cfg.adx_period)
        elif ind in TWO_TF_SUPERTRENDS and resolved(ind, params)["tf"] == "chart":
            need = max(need, 3 * int(resolved(ind, params)["period"]))
    return min(need, MAX_WARMUP)


def other_timeframes(wanted: list[str], params: dict | None, chart_code: str) -> set[str]:
    """Timeframes the two-timeframe Supertrend needs fetched besides the chart's."""
    out = set()
    for ind in TWO_TF_SUPERTRENDS:
        if ind in wanted:
            code = resolved(ind, params)["tf"]
            if code != "chart" and code != chart_code:
                out.add(code)
    return out


# ---------------------------------------------------------------- series
def _points(times: list[int], values: np.ndarray) -> list[dict]:
    """Drop NaN warmup values; Lightweight Charts wants gaps omitted, not nulled."""
    out: list[dict] = []
    for t, v in zip(times, values):
        f = float(v)
        if f == f:  # NaN check without importing math
            out.append({"time": t, "value": round(f, 4)})
    return out


def _trend_points(times: list[int], line: np.ndarray, direction: np.ndarray) -> list[dict]:
    rows: list[dict] = []
    for t, v, d in zip(times, line, direction):
        f = float(v)
        if f == f:
            rows.append(
                {
                    "time": t,
                    "value": round(f, 4),
                    # -1 is an uptrend (line below price), +1 a downtrend. The charts
                    # page splits on this so each side takes its own user-chosen
                    # colour; `color` is only the default for other clients.
                    "trend": -1 if d == -1 else 1,
                    "color": "#3fb950" if d == -1 else "#f85149",
                }
            )
    return rows


def _end(t: int, minutes: int, segment: str) -> int:
    return int(bar_end(datetime.fromtimestamp(t, IST), minutes, segment).timestamp())


def htf_supertrend(
    bars: list[Bar],
    htf_bars: list[Bar],
    chart_minutes: int,
    htf_minutes: int,
    period: int,
    factor: float,
    segment: str = "NSE_EQ",
) -> list[dict]:
    """Another timeframe's Supertrend, one point per chart bar.

    Higher timeframe: the chart bar that closes a higher bar takes that bar's own
    value; one inside it takes the value the higher bar had at that moment - the last
    closed higher bar's state stepped once with the higher bar so far (high and low
    of the chart bars in it, close of this one). Lower timeframe: the last lower bar
    that began before the chart bar ended.
    """
    if not bars or not htf_bars:
        return []
    states = supertrend_states(
        [b.high for b in htf_bars], [b.low for b in htf_bars], [b.close for b in htf_bars],
        period, factor,
    )
    starts = [b.time for b in htf_bars]
    ends = [_end(b.time, htf_minutes, segment) for b in htf_bars]
    out: list[dict] = []
    current = -1
    hi = lo = 0.0
    for b in bars:
        k = bisect_right(starts, b.time) - 1
        if k < 0:
            continue
        chart_end = _end(b.time, chart_minutes, segment)
        if htf_minutes <= chart_minutes:
            k2 = bisect_left(starts, chart_end) - 1
            state = states[k2] if k2 >= 0 else None
        else:
            if k != current:
                current, hi, lo = k, b.high, b.low
            else:
                hi, lo = max(hi, b.high), min(lo, b.low)
            if chart_end >= ends[k]:
                state = states[k]
            else:
                state = supertrend_step(states[k - 1] if k > 0 else None, hi, lo, b.close,
                                        period, factor)
        if state is None or math.isnan(state.line):
            continue
        out.append({"time": b.time, "value": round(state.line, 4),
                    "trend": -1 if state.direction == -1 else 1})
    return out


def compute(
    bars: list[Bar],
    cfg: StrategyConfig,
    wanted: list[str] | None = None,
    *,
    params: dict | None = None,
    other: dict[str, list[Bar]] | None = None,
    minutes: int | None = None,
    segment: str = "NSE_EQ",
) -> dict[str, list[dict]]:
    """Indicator series keyed by catalog id, aligned to the given bars.

    `other` holds bars of other timeframes, keyed by code, for the two-timeframe
    Supertrend (see other_timeframes); `minutes` is the chart's own timeframe.
    """
    ids = [i for i in (wanted or DEFAULT_IDS) if i in CATALOG_IDS]
    if not bars or not ids:
        return {}

    times = [b.time for b in bars]
    high = np.array([b.high for b in bars], dtype=float)
    low = np.array([b.low for b in bars], dtype=float)
    close = np.array([b.close for b in bars], dtype=float)
    volume = np.array([b.volume for b in bars], dtype=float)
    # VWAP resets per trading day, so bars are grouped by their IST date.
    sessions = [datetime.fromtimestamp(t, IST).date() for t in times]

    out: dict[str, list[dict]] = {}

    if "vwap" in ids:
        out["vwap"] = _points(times, session_vwap(high, low, close, volume, sessions))

    if "ema_price" in ids:
        out["ema_price"] = _points(times, ema(close, cfg.price_ema_period))

    if "supertrend" in ids:
        line, direction = supertrend(
            high, low, close, cfg.supertrend_period, cfg.supertrend_factor
        )
        out["supertrend"] = _trend_points(times, line, direction)

    for ind in ("zema_fast", "zema_slow"):
        if ind in ids:
            out[ind] = _points(times, zema(close, int(resolved(ind, params)["period"])))

    for ind in TWO_TF_SUPERTRENDS:
        if ind not in ids:
            continue
        p = resolved(ind, params)
        period, factor, code = int(p["period"]), float(p["factor"]), p["tf"]
        other_minutes = CODE_MINUTES.get(code) if code != "chart" else minutes
        if code == "chart" or other_minutes == minutes or minutes is None:
            line, direction = supertrend(high, low, close, period, factor)
            out[ind] = _trend_points(times, line, direction)
        else:
            out[ind] = htf_supertrend(bars, (other or {}).get(code) or [], minutes,
                                      other_minutes, period, factor, segment)

    needs_rsi = {"rsi", "rsi_signal_entry", "rsi_signal_exit"} & set(ids)
    if needs_rsi:
        rsi_values = rsi_ind(close, cfg.rsi_period)
        if "rsi" in ids:
            out["rsi"] = _points(times, rsi_values)
        if "rsi_signal_entry" in ids:
            out["rsi_signal_entry"] = _points(
                times, ema_of(rsi_values, cfg.rsi_signal_entry_period)
            )
        if "rsi_signal_exit" in ids:
            out["rsi_signal_exit"] = _points(
                times, ema_of(rsi_values, cfg.rsi_signal_exit_period)
            )

    if "adx" in ids:
        out["adx"] = _points(times, adx_ind(high, low, close, cfg.adx_period, cfg.adx_period))

    return out


def catalog(cfg: StrategyConfig) -> list[dict]:
    """The catalog with period numbers filled in from the live config."""
    labels = {
        "ema_price": f"EMA({cfg.price_ema_period}) on price",
        "supertrend": f"Supertrend ({cfg.supertrend_period}, {cfg.supertrend_factor})",
        "rsi": f"RSI({cfg.rsi_period})",
        "rsi_signal_entry": f"EMA(RSI, {cfg.rsi_signal_entry_period}) — entry line",
        "rsi_signal_exit": f"EMA(RSI, {cfg.rsi_signal_exit_period}) — exit line",
        "adx": f"ADX({cfg.adx_period})",
    }
    out = []
    for item in CATALOG:
        entry = dict(item)
        entry["label"] = labels.get(item["id"], item["label"])
        entry["params"] = [dict(p) for p in item.get("params", ())]
        out.append(entry)
    return out
