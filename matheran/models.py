"""Domain models: instruments, watches, approvals, orders, positions, trades."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .timeutil import now_ist, to_ist


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class WatchState(str, Enum):
    WATCHING = "watching"           # scanning for an entry signal
    PENDING_APPROVAL = "pending_approval"  # signal found, waiting for you
    GTT_PENDING = "gtt_pending"     # manual GTT order held by the engine until its trigger
    ENTRY_PLACED = "entry_placed"   # buy order live at the broker
    IN_POSITION = "in_position"     # filled, monitoring exits
    EXIT_PLACED = "exit_placed"     # sell order live
    PAUSED = "paused"
    DONE = "done"                   # hit max trades for the day


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Direction(str, Enum):
    """Which way a watch trades.

    LONG buys to open and sells to close; SHORT sells to open and buys back to
    close. Every entry and exit condition is mirrored, and the stop sits above the
    entry for a short instead of below it.
    """

    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def sign(self) -> int:
        """+1 for long, -1 for short. Used so P&L and stop maths stay one formula."""
        return 1 if self is Direction.LONG else -1

    @property
    def entry_side(self) -> Side:
        return Side.BUY if self is Direction.LONG else Side.SELL

    @property
    def exit_side(self) -> Side:
        return Side.SELL if self is Direction.LONG else Side.BUY


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_MARKET = "STOP_LOSS_MARKET"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    PART_FILLED = "PART_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


TERMINAL_ORDER_STATUSES = {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED}


class ExitReason(str, Enum):
    RSI_BELOW_SIGNAL = "rsi_below_exit_signal"
    BELOW_SUPERTREND = "price_below_supertrend"
    EXIT_RULE = "exit_rule"          # one of the Strategy tab's exit conditions held
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"  # the stop had trailed up before it was hit
    TRAILING_PROFIT = "trailing_profit"  # the profit trail had locked in a gain
    TARGET = "target"
    SQUARE_OFF = "eod_square_off"
    MANUAL = "manual"
    HALT = "halt"


# INTRADAY is squared off at the square-off time; DELIVERY is carried (CNC for shares,
# NRML for futures and options) and only closes on its exits.
PRODUCTS = ("INTRADAY", "DELIVERY")
# What may close a position:
#   both      - stop loss / target / trailing, and the Strategy tab's exit conditions
#   sl_target - stop loss / target / trailing only
#   strategy  - the exit conditions only: no stop, no target, no trailing
EXIT_MODES = ("both", "sl_target", "strategy")
EXIT_MODE_TEXT = {
    "both": "SL / target and exit conditions",
    "sl_target": "SL / target only",
    "strategy": "exit conditions only",
}
CASH_SEGMENTS = {"NSE_EQ", "BSE_EQ"}


def exit_mode_of(value: Any, use_exit_rules: Any = True) -> str:
    """A stored exit mode, or the one an older record described with use_exit_rules."""
    text = str(value or "").strip().lower()
    if text in EXIT_MODES:
        return text
    return "both" if use_exit_rules in (None, True, "true", "True", 1) else "sl_target"


def product_of(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if text in PRODUCTS else "INTRADAY"


@dataclass(slots=True)
class Instrument:
    security_id: str
    symbol: str
    segment: str                 # NSE_EQ, NSE_FNO, BSE_EQ, ...
    instrument_type: str         # EQUITY, OPTIDX, OPTSTK, FUTIDX, INDEX
    display_name: str = ""
    lot_size: int = 1
    tick_size: float = 0.05
    expiry: str | None = None
    strike: float | None = None
    option_type: str | None = None  # CE | PE
    underlying: str | None = None
    # Provider-specific identifier for the market-data source, when it differs from
    # security_id (e.g. Upstox's "NSE_EQ|INE002A01018").
    data_key: str | None = None

    @property
    def is_option(self) -> bool:
        return self.instrument_type in {"OPTIDX", "OPTSTK", "OPTFUT", "OPTCUR"}

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class OrderRef:
    broker_order_id: str
    correlation_id: str
    side: Side
    order_type: OrderType
    quantity: int
    price: float = 0.0
    trigger_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    average_price: float = 0.0
    message: str = ""
    placed_at: datetime = field(default_factory=now_ist)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["side"] = self.side.value
        d["order_type"] = self.order_type.value
        d["status"] = self.status.value
        d["placed_at"] = self.placed_at.isoformat()
        return d


@dataclass(slots=True)
class Snapshot:
    """Indicator values at the last closed candle, for display and audit."""

    candle_ts: datetime | None = None
    ltp: float | None = None
    close: float | None = None
    vwap: float | None = None
    rsi: float | None = None
    rsi_signal_entry: float | None = None
    rsi_signal_exit: float | None = None
    supertrend: float | None = None
    supertrend_direction: int | None = None
    price_ema: float | None = None
    adx: float | None = None
    bars: int = 0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["candle_ts"] = self.candle_ts.isoformat() if self.candle_ts else None
        return d


@dataclass(slots=True)
class SignalResult:
    ready: bool
    checks: dict[str, bool]
    reasons: list[str]
    snapshot: Snapshot

    def as_dict(self) -> dict:
        return {
            "ready": self.ready,
            "checks": self.checks,
            "reasons": self.reasons,
            "snapshot": self.snapshot.as_dict(),
        }


@dataclass(slots=True)
class Approval:
    id: str
    watch_id: str
    instrument: Instrument
    quantity: int
    reference_price: float
    stop_price: float
    target_price: float | None
    snapshot: Snapshot
    checks: dict[str, bool]
    created_at: datetime
    expires_at: datetime
    direction: Direction = Direction.LONG
    status: str = "pending"  # pending | approved | rejected | expired
    decided_at: datetime | None = None
    note: str = ""
    product: str = "INTRADAY"
    exit_mode: str = "both"

    @property
    def capital(self) -> float:
        return self.reference_price * self.quantity

    @property
    def risk_amount(self) -> float:
        if self.exit_mode == "strategy":
            return 0.0  # no stop: the exit conditions alone decide
        return abs(self.reference_price - self.stop_price) * self.quantity

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "watch_id": self.watch_id,
            "direction": self.direction.value,
            "side": self.direction.entry_side.value,
            "instrument": self.instrument.as_dict(),
            "quantity": self.quantity,
            "reference_price": self.reference_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "product": self.product,
            "exit_mode": self.exit_mode,
            "capital_deployed": round(self.capital, 2),
            "risk_amount": round(self.risk_amount, 2),
            "snapshot": self.snapshot.as_dict(),
            "checks": self.checks,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "status": self.status,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "note": self.note,
        }


TICKET_ORDER_TYPES = ("MARKET", "LIMIT", "GTT")
SL_UNITS = ("pct", "price")
TRAIL_UNITS = ("pct", "pts")
TARGET_UNITS = ("pct", "price")


def _fmt_level(value: float | None, unit: str) -> str:
    if value is None:
        return ""
    if unit == "pct":
        return f"{value:g}%"
    if unit == "pts":
        return f"{value:g} pts"
    return f"{value:.2f}"


@dataclass(slots=True)
class TradeTicket:
    """A manual order from the charts page: how to get in, and how to get out.

    Held on the watch until the entry fills, when it becomes the position's stop,
    target and trailing distance. A GTT waits in the engine until the live price
    reaches `trigger_price`, then sends a market order, or a limit order at
    `limit_price` when one is set.
    """

    direction: Direction
    quantity: int
    order_type: str = "MARKET"           # MARKET | LIMIT | GTT
    limit_price: float | None = None     # LIMIT, or the order a triggered GTT sends
    trigger_price: float | None = None   # GTT only
    trigger_above: bool = True           # GTT fires on LTP >= trigger, else LTP <= trigger
    sl_value: float | None = None
    sl_unit: str = "pct"                 # pct of entry | absolute price
    trail_value: float | None = None
    trail_unit: str = "pct"              # pct of the best price | points
    # Trailing profit: the trail only starts once the trade is this % in profit.
    # None trails from the entry, as a plain trailing stop does.
    trail_trigger_pct: float | None = None
    target_value: float | None = None
    target_unit: str = "pct"             # pct of entry | absolute price
    exit_mode: str = "both"              # both | sl_target | strategy (see EXIT_MODES)
    product: str = "INTRADAY"            # INTRADAY | DELIVERY
    timeframe_minutes: int | None = None  # candles the exit rules read (the chart's)
    note: str = ""
    created_at: datetime = field(default_factory=now_ist)

    @property
    def use_exit_rules(self) -> bool:
        return self.exit_mode != "sl_target"

    def exits_text(self) -> str:
        parts = []
        if self.exit_mode != "strategy":
            if self.sl_value:
                parts.append("SL " + _fmt_level(self.sl_value, self.sl_unit))
            if self.trail_value:
                parts.append("trail " + _fmt_level(self.trail_value, self.trail_unit)
                             + (f" after {self.trail_trigger_pct:g}% profit"
                                if self.trail_trigger_pct else ""))
            if self.target_value:
                parts.append("target " + _fmt_level(self.target_value, self.target_unit))
        if self.exit_mode != "both":
            parts.append(EXIT_MODE_TEXT.get(self.exit_mode, self.exit_mode))
        if self.product == "DELIVERY":
            parts.append("delivery")
        return " · ".join(parts)

    def describe(self) -> str:
        side = self.direction.entry_side.value
        if self.order_type == "GTT":
            head = (f"GTT {side} {self.quantity} when LTP {'≥' if self.trigger_above else '≤'} "
                    f"{self.trigger_price:.2f}, then "
                    + (f"limit {self.limit_price:.2f}" if self.limit_price else "market"))
        elif self.order_type == "LIMIT":
            head = f"LIMIT {side} {self.quantity} @ {self.limit_price:.2f}"
        else:
            head = f"MARKET {side} {self.quantity}"
        exits = self.exits_text()
        return head + (f" · {exits}" if exits else "")

    def as_dict(self) -> dict:
        return {
            "direction": self.direction.value,
            "side": self.direction.entry_side.value,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "trigger_price": self.trigger_price,
            "trigger_above": self.trigger_above,
            "sl_value": self.sl_value,
            "sl_unit": self.sl_unit,
            "trail_value": self.trail_value,
            "trail_unit": self.trail_unit,
            "trail_trigger_pct": self.trail_trigger_pct,
            "target_value": self.target_value,
            "target_unit": self.target_unit,
            "exit_mode": self.exit_mode,
            "use_exit_rules": self.use_exit_rules,
            "product": self.product,
            "timeframe_minutes": self.timeframe_minutes,
            "note": self.note,
            "created_at": self.created_at.isoformat(),
            "text": self.describe(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TradeTicket":
        def num(key):
            v = data.get(key)
            return None if v in (None, "") else float(v)

        created = data.get("created_at")
        try:
            ts = to_ist(datetime.fromisoformat(str(created))) if created else now_ist()
        except ValueError:
            ts = now_ist()
        return cls(
            direction=Direction(str(data.get("direction", "LONG")).upper()),
            quantity=int(data.get("quantity", 0)),
            order_type=str(data.get("order_type", "MARKET")).upper(),
            limit_price=num("limit_price"),
            trigger_price=num("trigger_price"),
            trigger_above=bool(data.get("trigger_above", True)),
            sl_value=num("sl_value"),
            sl_unit=str(data.get("sl_unit") or "pct"),
            trail_value=num("trail_value"),
            trail_unit=str(data.get("trail_unit") or "pct"),
            trail_trigger_pct=num("trail_trigger_pct"),
            target_value=num("target_value"),
            target_unit=str(data.get("target_unit") or "pct"),
            exit_mode=exit_mode_of(data.get("exit_mode"), data.get("use_exit_rules", True)),
            product=product_of(data.get("product")),
            timeframe_minutes=int(data["timeframe_minutes"]) if data.get("timeframe_minutes") else None,
            note=str(data.get("note", "")),
            created_at=ts,
        )


@dataclass(slots=True)
class Position:
    instrument: Instrument
    quantity: int
    entry_price: float
    entry_time: datetime
    stop_price: float
    target_price: float | None
    direction: Direction = Direction.LONG
    entry_order_id: str | None = None
    stop_order_id: str | None = None
    # Trailing stop: the stop follows the best price since entry at this distance and
    # never moves back. pct = % of that best price, pts = points.
    trail_unit: str | None = None
    trail_value: float | None = None
    # Trailing profit: the trail waits until the best price is this % in profit.
    trail_trigger_pct: float | None = None
    best_price: float | None = None
    trailed: bool = False                    # the trail has moved the stop at least once
    broker_stop_price: float | None = None   # where the resting broker stop order sits
    exit_mode: str = "both"                  # both | sl_target | strategy (EXIT_MODES)
    exit_timeframe: int | None = None        # candles those rules read; None = the watch's
    product: str = "INTRADAY"                # INTRADAY is squared off; DELIVERY is carried

    @property
    def use_exit_rules(self) -> bool:
        """The Strategy tab's exit conditions can close it."""
        return self.exit_mode != "sl_target"

    @property
    def price_exits(self) -> bool:
        """The stop, target and trailing levels can close it."""
        return self.exit_mode != "strategy"

    def trail_active(self, best: float | None = None) -> bool:
        """Whether the trail is following the price yet (a trailing profit waits for
        its trigger; a plain trailing stop follows from the entry)."""
        if not self.trail_value:
            return False
        if not self.trail_trigger_pct:
            return True
        best = best if best is not None else (self.best_price or self.entry_price)
        gain = (best - self.entry_price) * self.direction.sign
        return gain >= self.entry_price * float(self.trail_trigger_pct) / 100.0

    def trail_distance(self, reference: float | None = None) -> float | None:
        if not self.trail_value:
            return None
        if self.trail_unit == "pts":
            return float(self.trail_value)
        base = reference if reference is not None else (self.best_price or self.entry_price)
        return base * float(self.trail_value) / 100.0

    def unrealised(self, ltp: float | None) -> float:
        if ltp is None:
            return 0.0
        return (ltp - self.entry_price) * self.quantity * self.direction.sign

    def stop_breached(self, ltp: float) -> bool:
        """A long stop sits below the entry, a short stop above it."""
        if self.direction is Direction.LONG:
            return ltp <= self.stop_price
        return ltp >= self.stop_price

    def target_reached(self, ltp: float) -> bool:
        if self.target_price is None:
            return False
        if self.direction is Direction.LONG:
            return ltp >= self.target_price
        return ltp <= self.target_price

    def as_dict(self, ltp: float | None = None) -> dict:
        return {
            "instrument": self.instrument.as_dict(),
            "quantity": self.quantity,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "entry_order_id": self.entry_order_id,
            "stop_order_id": self.stop_order_id,
            "trail_unit": self.trail_unit,
            "trail_value": self.trail_value,
            "trail_trigger_pct": self.trail_trigger_pct,
            "trail_active": self.trail_active(),
            "best_price": self.best_price,
            "trailed": self.trailed,
            "broker_stop_price": self.broker_stop_price,
            "exit_mode": self.exit_mode,
            "use_exit_rules": self.use_exit_rules,
            "price_exits": self.price_exits,
            "exit_timeframe": self.exit_timeframe,
            "product": self.product,
            "ltp": ltp,
            "unrealised_pnl": round(self.unrealised(ltp), 2),
        }


@dataclass(slots=True)
class Trade:
    id: str
    watch_id: str
    instrument: Instrument
    quantity: int
    entry_price: float
    entry_time: datetime
    exit_price: float
    exit_time: datetime
    exit_reason: ExitReason
    mode: str
    direction: Direction = Direction.LONG
    entry_snapshot: Snapshot | None = None
    exit_snapshot: Snapshot | None = None
    # What exactly closed it, in words: which exit condition held, or the stop level.
    exit_note: str = ""
    product: str = "INTRADAY"

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.quantity * self.direction.sign

    @property
    def pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        move = (self.exit_price - self.entry_price) / self.entry_price * 100.0
        return move * self.direction.sign

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "watch_id": self.watch_id,
            "instrument": self.instrument.as_dict(),
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "exit_price": self.exit_price,
            "exit_time": self.exit_time.isoformat(),
            "exit_reason": self.exit_reason.value,
            "mode": self.mode,
            "direction": self.direction.value,
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 3),
            "entry_snapshot": self.entry_snapshot.as_dict() if self.entry_snapshot else None,
            "exit_snapshot": self.exit_snapshot.as_dict() if self.exit_snapshot else None,
            "exit_note": self.exit_note,
            "product": self.product,
        }


@dataclass(slots=True)
class Watch:
    """One instrument being monitored, with its own risk and lifecycle."""

    id: str
    instrument: Instrument
    quantity: int
    timeframe_minutes: int
    stop_loss_pct: float
    target_pct: float | None
    kind: str = "equity"  # equity | option
    # Direction of the current (or most recent) trade. For a watch that trades both
    # ways this flips to whichever side signalled.
    direction: Direction = Direction.LONG
    # Which signals the watch acts on: LONG, SHORT, or BOTH - buy when the long
    # conditions hold, sell when their mirror image does. One position at a time.
    sides: str = "LONG"
    # Candle source used by the fixed BUY/SELL entry conditions.
    candle_type: str = "normal"
    # Never raise its own approvals; only enters when told to (a basket leg that is
    # executed together with its basket). Exits still run as normal.
    manual_only: bool = False
    require_adx: bool = False
    adx_min: float | None = None
    state: WatchState = WatchState.WATCHING
    created_at: datetime = field(default_factory=now_ist)
    updated_at: datetime = field(default_factory=now_ist)

    approval_id: str | None = None
    entry_order: OrderRef | None = None
    exit_order: OrderRef | None = None
    position: Position | None = None

    trades_today: int = 0
    trade_day: str = ""
    cooldown_until: datetime | None = None
    last_signal: SignalResult | None = None
    last_error: str = ""
    notes: str = ""
    # Set when this watch is one leg of a basket, so legs can be grouped and exited
    # together while each still carries its own stop.
    basket_id: str | None = None
    # A manual order from the charts page that has not filled yet (see TradeTicket).
    ticket: TradeTicket | None = None
    # The chart symbol id the last manual order was placed from, so the charts page
    # can find this watch again whatever id form it was opened with.
    chart_symbol: str = ""
    # INTRADAY or DELIVERY for the trades this watch opens on its signal.
    product: str = "INTRADAY"
    # How its positions exit (EXIT_MODES); "" follows the Strategy tab's default.
    exit_mode: str = ""
    # Which side last_signal was evaluated for (a BOTH watch checks both), and when.
    signal_side: str = ""
    signal_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = now_ist()

    def as_dict(self, ltp: float | None = None) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "direction": self.direction.value,
            "sides": self.sides,
            "candle_type": self.candle_type,
            "manual_only": self.manual_only,
            "instrument": self.instrument.as_dict(),
            "quantity": self.quantity,
            "timeframe_minutes": self.timeframe_minutes,
            "stop_loss_pct": self.stop_loss_pct,
            "target_pct": self.target_pct,
            "require_adx": self.require_adx,
            "adx_min": self.adx_min,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "approval_id": self.approval_id,
            "entry_order": self.entry_order.as_dict() if self.entry_order else None,
            "exit_order": self.exit_order.as_dict() if self.exit_order else None,
            "position": self.position.as_dict(ltp) if self.position else None,
            "trades_today": self.trades_today,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "last_signal": self.last_signal.as_dict() if self.last_signal else None,
            "last_error": self.last_error,
            "notes": self.notes,
            "basket_id": self.basket_id,
            "ticket": self.ticket.as_dict() if self.ticket else None,
            "chart_symbol": self.chart_symbol,
            "product": self.product,
            "exit_mode": self.exit_mode,
            "signal_side": self.signal_side,
            "signal_at": self.signal_at.isoformat() if self.signal_at else None,
        }


@dataclass(slots=True)
class OiStats:
    """Open-interest picture for one contract.

    `change` is versus the previous session's close, which is the number quoted as
    "OI change" on a chain. `buildup` is the change over the last few minutes, which
    is what tells you whether positions are being added right now.
    """

    oi: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    buildup: float = 0.0          # change over buildup_minutes
    buildup_minutes: int = 5
    volume: float = 0.0           # traded volume this session
    prev_close_oi: float = 0.0

    @property
    def interpretation(self) -> str:
        """Standard chain reading of price direction against OI direction."""
        if self.buildup == 0:
            return "flat"
        return "adding" if self.buildup > 0 else "unwinding"

    def as_dict(self) -> dict:
        return {
            "oi": self.oi,
            "oi_change": self.change,
            "oi_change_pct": round(self.change_pct, 2),
            "oi_buildup": self.buildup,
            "oi_buildup_minutes": self.buildup_minutes,
            "volume": self.volume,
            "prev_close_oi": self.prev_close_oi,
            "oi_trend": self.interpretation,
        }


@dataclass(slots=True)
class OptionRow:
    """One row of the ATM +/- OTM options table."""

    instrument: Instrument
    moneyness: str          # ATM, OTM+1 ... OTM+5
    snapshot: Snapshot
    price_above_vwap: bool
    entry_ready: bool
    checks: dict[str, bool]
    reasons: list[str]
    oi: OiStats = field(default_factory=OiStats)
    error: str = ""

    def as_dict(self) -> dict:
        snap = self.snapshot
        return {
            "security_id": self.instrument.security_id,
            "symbol": self.instrument.symbol,
            "display_name": self.instrument.display_name,
            "expiry": self.instrument.expiry,
            "strike": self.instrument.strike,
            "option_type": self.instrument.option_type,
            "lot_size": self.instrument.lot_size,
            "moneyness": self.moneyness,
            "ltp": snap.ltp,
            "vwap": snap.vwap,
            "rsi": snap.rsi,
            "rsi_ema_21": snap.rsi_signal_entry,
            "rsi_ema_9": snap.rsi_signal_exit,
            "price_ema_21": snap.price_ema,
            "supertrend": snap.supertrend,
            "supertrend_direction": snap.supertrend_direction,
            "adx": snap.adx,
            "bars": snap.bars,
            "candle_ts": snap.candle_ts.isoformat() if snap.candle_ts else None,
            "price_above_vwap": self.price_above_vwap,
            "entry_ready": self.entry_ready,
            "checks": self.checks,
            "reasons": self.reasons,
            **self.oi.as_dict(),
            "error": self.error,
        }


def round_to_tick(price: float, tick: float, mode: str = "nearest") -> float:
    """Snap a price to the instrument's tick size. Exchanges reject off-tick prices."""
    if tick <= 0:
        return round(price, 2)
    steps = price / tick
    if mode == "down":
        import math

        n = math.floor(steps + 1e-9)
    elif mode == "up":
        import math

        n = math.ceil(steps - 1e-9)
    else:
        n = round(steps)
    return round(n * tick, 4)


def coerce_any(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
