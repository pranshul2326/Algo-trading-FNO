"""Exit rules: rows of `indicator  comparison  indicator-or-number`, joined by AND / OR.

A row reads the way you would say it:

        RSI(21)  crosses below  EMA(RSI(21), 9)        on candle close
    OR  Close    below          Supertrend(21, 0.618)  on candle close

Grouping follows Pine Script and Python: AND binds tighter than OR, so
``A AND B OR C`` means ``(A AND B) OR C``. The rule text shown in the console spells
the grouping out with brackets so it cannot be misread.

Each row is checked either

  * ``close`` - on the last CLOSED candle of the watch's timeframe. A position only
    listens to candles that closed after it was opened, so a condition that was
    already true when you bought cannot sell you straight back out; or
  * ``live``  - on the candle still forming, with its close replaced by the live
    price, so it can fire between candle closes.

Rules are written for a long position. A short uses the mirror image: above <->
below and crosses above <-> crosses below; RSI levels reflect around 50 (70 <-> 30);
ADX and ATR carry no direction and stay as written; +DI and -DI swap.

Everything here is plain data (dicts of numbers and strings), so rules round-trip
through config.yaml and JSON without a schema layer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .candles import Candle, CandleSeries, bar_end
from .indicators import atr, dmi, ema, ema_of, rsi, session_vwap, sma, supertrend

MAX_RULES = 12
JOINS = ("AND", "OR")


def _int(key: str, label: str, default: int, lo: int, hi: int) -> dict:
    return {"key": key, "label": label, "type": "int", "default": default, "min": lo, "max": hi}


def _float(key: str, label: str, default: float, lo: float, hi: float, step: float = 0.01) -> dict:
    return {"key": key, "label": label, "type": "float", "default": default, "min": lo,
            "max": hi, "step": step}


# `kind` decides how a row is mirrored for a short position (see mirror_rule).
OPERANDS: dict[str, dict] = {
    "close": {"label": "Close", "kind": "price", "params": ()},
    "open": {"label": "Open", "kind": "price", "params": ()},
    "high": {"label": "High", "kind": "price", "params": ()},
    "low": {"label": "Low", "kind": "price", "params": ()},
    "vwap": {"label": "VWAP (session)", "kind": "price", "params": ()},
    "ema": {"label": "EMA of close", "kind": "price",
            "params": (_int("period", "Period", 21, 1, 500),)},
    "sma": {"label": "SMA of close", "kind": "price",
            "params": (_int("period", "Period", 20, 1, 500),)},
    "supertrend": {"label": "Supertrend", "kind": "price",
                   "params": (_int("period", "ATR period", 21, 1, 500),
                              _float("factor", "Factor", 0.618, 0.001, 50.0, 0.001))},
    "rsi": {"label": "RSI", "kind": "oscillator",
            "params": (_int("period", "Period", 21, 2, 500),)},
    "rsi_ema": {"label": "EMA of RSI", "kind": "oscillator",
                "params": (_int("rsi", "RSI period", 21, 2, 500),
                           _int("period", "EMA period", 9, 1, 500))},
    "adx": {"label": "ADX", "kind": "strength",
            "params": (_int("period", "Period", 14, 2, 500),)},
    "plus_di": {"label": "+DI", "kind": "di", "params": (_int("period", "Period", 14, 2, 500),)},
    "minus_di": {"label": "-DI", "kind": "di", "params": (_int("period", "Period", 14, 2, 500),)},
    "atr": {"label": "ATR", "kind": "strength",
            "params": (_int("period", "Period", 14, 1, 500),)},
    "value": {"label": "Number", "kind": "value",
              "params": (_float("value", "Value", 0.0, -1e9, 1e9),)},
}

COMPARATORS: dict[str, dict] = {
    "crosses_below": {"label": "crosses below", "past": "crossed below", "mirror": "crosses_above"},
    "crosses_above": {"label": "crosses above", "past": "crossed above", "mirror": "crosses_below"},
    "below": {"label": "below", "past": "is below", "mirror": "above"},
    "above": {"label": "above", "past": "is above", "mirror": "below"},
    "at_or_below": {"label": "at or below", "past": "is at or below", "mirror": "at_or_above"},
    "at_or_above": {"label": "at or above", "past": "is at or above", "mirror": "at_or_below"},
}
_OP_ALIASES = {"<": "below", ">": "above", "<=": "at_or_below", ">=": "at_or_above",
               "cross_below": "crosses_below", "cross_above": "crosses_above"}

EVAL_ON = {
    "close": "on candle close",
    "live": "live price",
}


# ------------------------------------------------------------------ catalog
def catalog() -> dict:
    """Everything the console needs to draw the rule builder."""
    return {
        "operands": [
            {"id": k, "label": v["label"], "kind": v["kind"],
             "params": [dict(p) for p in v["params"]], "left": k != "value"}
            for k, v in OPERANDS.items()
        ],
        "comparators": [{"id": k, "label": v["label"]} for k, v in COMPARATORS.items()],
        "joins": list(JOINS),
        "on": [{"id": k, "label": v} for k, v in EVAL_ON.items()],
        "max_rules": MAX_RULES,
    }


# ------------------------------------------------------------ normalisation
def _param(value, spec: dict, where: str):
    if value is None or (isinstance(value, str) and not value.strip()):
        value = spec["default"]
    label = spec["label"].lower()
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: {label} must be a number, got {value!r}") from None
    if not math.isfinite(num):
        raise ValueError(f"{where}: {label} must be a finite number")
    if spec["type"] == "int":
        if not num.is_integer():
            raise ValueError(f"{where}: {label} must be a whole number, got {value}")
        num = int(num)
    if num < spec["min"] or num > spec["max"]:
        raise ValueError(
            f"{where}: {label} must be between {spec['min']:g} and {spec['max']:g}, got {num:g}"
        )
    return num


def _operand(raw, where: str) -> dict:
    # A bare number on either side is shorthand for a Number operand, a bare string
    # for an indicator with default parameters. Handy when editing config.yaml.
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = {"ind": "value", "value": raw}
    elif isinstance(raw, str):
        raw = {"ind": raw}
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected an indicator, got {raw!r}")
    ind = str(raw.get("ind") or "").strip().lower()
    spec = OPERANDS.get(ind)
    if spec is None:
        raise ValueError(
            f"{where}: unknown indicator '{ind}'. Available: {', '.join(OPERANDS)}"
        )
    out: dict = {"ind": ind}
    for p in spec["params"]:
        out[p["key"]] = _param(raw.get(p["key"]), p, f"{where} ({spec['label']})")
    return out


def normalize_rules(raw) -> list[dict] | None:
    """Validate rows and fill in defaults. None stays None (use the legacy flags)."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise ValueError("strategy.exit_rules must be a list of rows")
    if len(raw) > MAX_RULES:
        raise ValueError(f"at most {MAX_RULES} exit conditions, got {len(raw)}")
    out: list[dict] = []
    for n, row in enumerate(raw, start=1):
        where = f"exit condition {n}"
        if not isinstance(row, dict):
            raise ValueError(f"{where}: expected a mapping, got {row!r}")
        join = str(row.get("join") or "AND").strip().upper()
        if join not in JOINS:
            raise ValueError(f"{where}: join must be AND or OR, got {join!r}")
        op = str(row.get("op") or "").strip().lower()
        op = _OP_ALIASES.get(op, op)
        if op not in COMPARATORS:
            raise ValueError(
                f"{where}: unknown condition {op!r}. Available: {', '.join(COMPARATORS)}"
            )
        on = str(row.get("on") or "close").strip().lower()
        if on not in EVAL_ON:
            raise ValueError(f"{where}: 'on' must be close or live, got {on!r}")
        left = _operand(row.get("left"), f"{where}, left side")
        if left["ind"] == "value":
            raise ValueError(f"{where}: the left side must be an indicator; put the number on the right")
        right = _operand(row.get("right"), f"{where}, right side")
        out.append({"join": "AND" if n == 1 else join, "left": left, "op": op,
                    "right": right, "on": on})
    return out


def legacy_rules(cfg) -> list[dict]:
    """The two exits an older config describes with flags, written as rows."""
    rows: list[dict] = []
    if getattr(cfg, "exit_on_rsi", True):
        rows.append({
            "join": "AND",
            "left": {"ind": "rsi", "period": int(cfg.rsi_period)},
            "op": "crosses_below" if cfg.exit_condition_mode == "cross" else "below",
            "right": {"ind": "rsi_ema", "rsi": int(cfg.rsi_period),
                      "period": int(cfg.rsi_signal_exit_period)},
            "on": "close",
        })
    if getattr(cfg, "exit_on_supertrend", True):
        rows.append({
            "join": "OR",
            "left": {"ind": "close"},
            "op": "below",
            "right": {"ind": "supertrend", "period": int(cfg.supertrend_period),
                      "factor": float(cfg.supertrend_factor)},
            "on": "close",
        })
    if rows:
        rows[0]["join"] = "AND"
    return rows


def effective_rules(cfg) -> list[dict]:
    """The rows the engine acts on: the configured ones, or the legacy two."""
    rules = getattr(cfg, "exit_rules", None)
    return list(rules) if rules is not None else legacy_rules(cfg)


def needs_live(rows: list[dict]) -> bool:
    return any(r.get("on") == "live" for r in rows or [])


# ---------------------------------------------------------------- warmup
def _operand_warmup(o: dict) -> int:
    """Bars needed before the operand's latest value is defined."""
    ind = o["ind"]
    p = int(o.get("period", 1) or 1)
    if ind in {"ema", "sma", "atr", "supertrend"}:
        return p
    if ind == "rsi":
        return p + 1
    if ind == "rsi_ema":
        return int(o.get("rsi", 1)) + p
    if ind == "adx":
        return 2 * p
    if ind in {"plus_di", "minus_di"}:
        return p + 1
    return 1


def _row_warmup(row: dict) -> int:
    extra = 1 if row["op"].startswith("crosses") else 0
    return max(_operand_warmup(row["left"]), _operand_warmup(row["right"])) + extra


def rules_warmup(rows: list[dict] | None) -> int:
    return max((_row_warmup(r) for r in rows or []), default=0)


# --------------------------------------------------------------- wording
def _num(v: float) -> str:
    return f"{v:g}"


def describe_operand(o: dict) -> str:
    ind = o["ind"]
    if ind == "value":
        return _num(float(o["value"]))
    if ind in {"close", "open", "high", "low"}:
        return OPERANDS[ind]["label"]
    if ind == "vwap":
        return "VWAP"
    if ind == "ema":
        return f"EMA({o['period']})"
    if ind == "sma":
        return f"SMA({o['period']})"
    if ind == "supertrend":
        return f"Supertrend({o['period']}, {_num(float(o['factor']))})"
    if ind == "rsi":
        return f"RSI({o['period']})"
    if ind == "rsi_ema":
        return f"EMA(RSI({o['rsi']}), {o['period']})"
    if ind == "adx":
        return f"ADX({o['period']})"
    if ind == "plus_di":
        return f"+DI({o['period']})"
    if ind == "minus_di":
        return f"-DI({o['period']})"
    if ind == "atr":
        return f"ATR({o['period']})"
    return ind


def describe_rule(row: dict, *, timing: bool = True) -> str:
    text = (
        f"{describe_operand(row['left'])} {COMPARATORS[row['op']]['label']} "
        f"{describe_operand(row['right'])}"
    )
    if timing:
        text += " (live)" if row.get("on") == "live" else " (on candle close)"
    return text


def groups(rows: list[dict]) -> list[list[int]]:
    """Row indexes grouped by OR. Each group is ANDed together."""
    out: list[list[int]] = []
    for i, row in enumerate(rows):
        if i == 0 or row.get("join") == "OR":
            out.append([i])
        else:
            out[-1].append(i)
    return out


def describe_rules(rows: list[dict]) -> str:
    if not rows:
        return "no indicator conditions (stop, target and square-off only)"
    gs = groups(rows)
    parts = []
    for g in gs:
        body = " AND ".join(describe_rule(rows[i]) for i in g)
        parts.append(f"({body})" if len(g) > 1 and len(gs) > 1 else body)
    return " OR ".join(parts)


# ------------------------------------------------------------ mirroring
_DI_SWAP = {"plus_di": "minus_di", "minus_di": "plus_di"}


def mirror_rule(row: dict) -> dict:
    """The same exit for a short position."""
    left, right = dict(row["left"]), dict(row["right"])
    new = {**row, "left": left, "right": right}
    kl = OPERANDS[left["ind"]]["kind"]
    kr = OPERANDS[right["ind"]]["kind"]
    if kl == "strength" and kr in {"strength", "value"}:
        return new  # ADX / ATR measure how strong a move is, not which way it goes
    if "di" in (kl, kr):
        # +DI is the long side's momentum and -DI the short side's.
        for side in (left, right):
            if side["ind"] in _DI_SWAP:
                side["ind"] = _DI_SWAP[side["ind"]]
        return new
    new["op"] = COMPARATORS[row["op"]]["mirror"]
    if kl == "oscillator" and kr == "value":
        right["value"] = round(100.0 - float(right["value"]), 6)
    return new


def mirror_rules(rows: list[dict]) -> list[dict]:
    return [mirror_rule(r) for r in rows]


def explain(rows: list[dict]) -> dict:
    """Plain-English reading for both directions, for the console."""
    return {
        "long": describe_rules(rows),
        "short": describe_rules(mirror_rules(rows)),
        "warmup_bars": rules_warmup(rows),
    }


# ----------------------------------------------------------- evaluation
class SeriesCalc:
    """Operand values over one candle series, each computed at most once."""

    def __init__(self, series: CandleSeries):
        self.series = series
        self.n = len(series)
        self._cache: dict[tuple, np.ndarray] = {}

    def values(self, o: dict) -> np.ndarray:
        key = tuple(sorted(o.items()))
        hit = self._cache.get(key)
        if hit is None:
            hit = self._compute(o)
            self._cache[key] = hit
        return hit

    def _compute(self, o: dict) -> np.ndarray:
        n = self.n
        ind = o["ind"]
        if n == 0:
            return np.full(0, np.nan)
        s = self.series
        if ind == "value":
            return np.full(n, float(o["value"]))
        if ind in {"close", "open", "high", "low"}:
            return getattr(s, ind)
        h, l, c = s.high, s.low, s.close
        if ind == "vwap":
            return session_vwap(h, l, c, s.volume, s.session_ids)
        if ind == "ema":
            return ema(c, int(o["period"]))
        if ind == "sma":
            return sma(c, int(o["period"]))
        if ind == "supertrend":
            return supertrend(h, l, c, int(o["period"]), float(o["factor"]))[0]
        if ind == "rsi":
            return rsi(c, int(o["period"]))
        if ind == "rsi_ema":
            base = self.values({"ind": "rsi", "period": int(o["rsi"])})
            return ema_of(base, int(o["period"]))
        if ind == "atr":
            return atr(h, l, c, int(o["period"]))
        if ind in {"adx", "plus_di", "minus_di"}:
            p = int(o["period"])
            adx_v, plus, minus = dmi(h, l, c, p, p)
            self._cache[tuple(sorted({"ind": "adx", "period": p}.items()))] = adx_v
            self._cache[tuple(sorted({"ind": "plus_di", "period": p}.items()))] = plus
            self._cache[tuple(sorted({"ind": "minus_di", "period": p}.items()))] = minus
            return {"adx": adx_v, "plus_di": plus, "minus_di": minus}[ind]
        return np.full(n, np.nan)


@dataclass(slots=True)
class RowResult:
    index: int
    text: str                  # the row as it is being applied (mirrored for a short)
    on: str
    state: str                 # true | false | waiting | unavailable
    detail: str = ""
    left: float | None = None
    right: float | None = None
    candle_ts: datetime | None = None

    @property
    def hit(self) -> bool:
        return self.state == "true"

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "text": self.text,
            "on": self.on,
            "state": self.state,
            "detail": self.detail,
            "left": self.left,
            "right": self.right,
            "candle_ts": self.candle_ts.isoformat() if self.candle_ts else None,
        }


@dataclass(slots=True)
class RulesOutcome:
    fired: bool
    rows: list[RowResult] = field(default_factory=list)
    text: str = ""             # why it fired, or a one-line holding status

    def as_dict(self) -> dict:
        return {"fired": self.fired, "text": self.text, "rows": [r.as_dict() for r in self.rows]}


def live_series(closed: CandleSeries, forming: Candle | None, ltp: float | None) -> CandleSeries:
    """Closed candles plus the one still forming, its close taken from the live price."""
    if forming is None:
        return closed
    bar = forming
    if ltp is not None and ltp > 0:
        bar = Candle(ts=forming.ts, open=forming.open, high=max(forming.high, ltp),
                     low=min(forming.low, ltp), close=float(ltp), volume=forming.volume,
                     oi=forming.oi)
    return CandleSeries([*closed.candles, bar])


def _row(i: int, rule: dict, calc: SeriesCalc, text: str) -> RowResult:
    on = rule["on"]
    n = calc.n
    candle = calc.series.last
    ts = candle.ts if candle else None
    if n == 0:
        return RowResult(i, text, on, "unavailable", "no candles yet")
    a = calc.values(rule["left"])
    b = calc.values(rule["right"])
    k = n - 1
    cur_a, cur_b = float(a[k]), float(b[k])
    ltxt, rname = describe_operand(rule["left"]), describe_operand(rule["right"])
    if math.isnan(cur_a) or math.isnan(cur_b):
        return RowResult(i, text, on, "unavailable",
                         f"{describe_rule(rule, timing=False)}: needs {_row_warmup(rule)} "
                         f"candles of history, have {n}", candle_ts=ts)
    rtxt = rname if rule["right"]["ind"] == "value" else f"{rname} {cur_b:.2f}"
    op = rule["op"]
    if op.startswith("crosses"):
        prev_a = float(a[k - 1]) if k >= 1 else math.nan
        prev_b = float(b[k - 1]) if k >= 1 else math.nan
        if math.isnan(prev_a) or math.isnan(prev_b):
            return RowResult(i, text, on, "unavailable",
                             f"{describe_rule(rule, timing=False)}: needs one more candle "
                             "to see a cross", cur_a, cur_b, ts)
        if op == "crosses_above":
            hit = prev_a <= prev_b and cur_a > cur_b
        else:
            hit = prev_a >= prev_b and cur_a < cur_b
    else:
        hit = {
            "above": cur_a > cur_b,
            "below": cur_a < cur_b,
            "at_or_above": cur_a >= cur_b,
            "at_or_below": cur_a <= cur_b,
        }[op]
    if hit:
        when = "live" if on == "live" else (f"on the {ts:%H:%M} candle" if ts else "on close")
        detail = f"{ltxt} {cur_a:.2f} {COMPARATORS[op]['past']} {rtxt} ({when})"
    else:
        detail = f"{ltxt} {cur_a:.2f} vs {rtxt}"
    return RowResult(i, text, on, "true" if hit else "false", detail, cur_a, cur_b, ts)


def evaluate(
    rows: list[dict],
    *,
    closed: CandleSeries,
    live: CandleSeries | None = None,
    short: bool = False,
    entry_time: datetime | None = None,
    timeframe_minutes: int = 1,
    segment: str = "NSE_EQ",
) -> RulesOutcome:
    """Check every row and combine them, AND before OR.

    `closed` holds closed candles only; `live` adds the forming one (see
    live_series). With `entry_time`, candle-close rows ignore any candle that had
    already closed when the position was opened.
    """
    rules = mirror_rules(rows) if short else list(rows)
    if not rules:
        return RulesOutcome(False, [], "holding: no indicator exit conditions set")

    calcs = {"close": SeriesCalc(closed)}
    if needs_live(rules):
        calcs["live"] = SeriesCalc(live if live is not None else closed)

    gate = ""
    last = closed.last
    if entry_time is not None and last is not None:
        minutes = max(1, int(timeframe_minutes))
        if bar_end(last.ts, minutes, segment) <= entry_time:
            from .timeframes import code_of

            gate = f"waiting for the first {code_of(minutes)} candle to close after entry"

    results: list[RowResult] = []
    for i, rule in enumerate(rules):
        text = describe_rule(rule)
        if rule["on"] == "close" and gate:
            results.append(RowResult(i, text, "close", "waiting", gate))
            continue
        results.append(_row(i, rule, calcs[rule["on"]], text))

    for g in groups(rules):
        if all(results[i].hit for i in g):
            return RulesOutcome(True, results, " AND ".join(results[i].detail for i in g))

    shown = [r.detail for r in results if r.detail and r.state != "waiting"][:3]
    text = "holding: " + " | ".join(shown) if shown else "holding"
    if any(r.state == "waiting" for r in results):
        text += ("; candle-close conditions are " if shown else ": ") + gate
    return RulesOutcome(False, results, text)
