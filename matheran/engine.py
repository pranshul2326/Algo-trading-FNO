"""The trading engine: one state machine per watch, gated on your approval.

Lifecycle
---------
    watching ──signal──> pending_approval ──you approve──> entry_placed
                              │                                 │
                        reject/expire                         filled
                              │                                 ▼
                              └──────────────────────────── in_position
                                                                │
                                        rsi/supertrend/stop/target/square-off
                                                                ▼
                                                           exit_placed ──> watching

Nothing enters a trade without an explicit approval, every time. After an exit the
watch re-arms and asks again on the next signal.

Manual orders from the charts page skip the signal but not the rails:

    watching ──market / limit──> entry_placed ──filled──> in_position
    watching ──GTT──> gtt_pending ──LTP reaches the trigger──> entry_placed

A limit entry rests at the broker until it fills, you cancel it, or the no-new-entry
cutoff. A GTT is held here, not at the broker, and only fires while entries are
allowed. Each manual order carries its own stop, trailing stop and target.

A position is closed by whichever comes first: the Strategy tab's exit conditions
(rules.py), the stop (trailed, if set), the target, or the square-off time.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from .brokers.base import Broker, BrokerError
from .candles import apply_candle_type, drop_forming, normalize_candle_type, resample
from .config import Config
from .models import (
    CASH_SEGMENTS,
    EXIT_MODES,
    PRODUCTS,
    SL_UNITS,
    TARGET_UNITS,
    TICKET_ORDER_TYPES,
    TRAIL_UNITS,
    Approval,
    Direction,
    ExitReason,
    Instrument,
    OrderRef,
    OrderStatus,
    OrderType,
    Position,
    Side,
    SignalResult,
    Snapshot,
    TERMINAL_ORDER_STATUSES,
    Trade,
    TradeTicket,
    Watch,
    WatchState,
    new_id,
    round_to_tick,
)
from . import workspaces as ws_mod
from .rules import RulesOutcome, effective_rules, explain, live_series, needs_live
from .store import Store
from .strategy import Indicators, evaluate_entry, exit_outcome
from .timeframes import MINUTES as TIMEFRAME_MINUTES
from .timeframes import code_of, load_series
from .timeutil import at, now_ist

log = logging.getLogger(__name__)

ENTRY_ORDER_TIMEOUT_SECONDS = 90
# A pending GTT is deliberately not active: nothing is at the broker yet, so it does
# not count against max_open_positions or block a broker swap.
ACTIVE_STATES = {WatchState.ENTRY_PLACED, WatchState.IN_POSITION, WatchState.EXIT_PLACED}
# Every timeframe the charts offer: 1m 3m 5m 9m 15m 30m 1h 2h 1D 1W 1M.
WATCH_TIMEFRAMES = TIMEFRAME_MINUTES
# Below an hour the six sessions of 1-minute candles the feed already serves are
# plenty; from an hour up, earlier sessions come from the provider's history.
HISTORY_FROM_MINUTES = 60
RESTING_STATUSES = {OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PART_FILLED}
ENTRY_ORDER_TYPES = ("MARKET", "LIMIT")


class EngineError(RuntimeError):
    pass


class Engine:
    def __init__(self, cfg: Config, broker: Broker, store: Store, now_fn=now_ist):
        self.cfg = cfg
        self.broker = broker
        self.store = store
        self.now = now_fn

        self.watches: dict[str, Watch] = {}
        self.approvals: dict[str, Approval] = {}
        self._watch_locks: dict[str, asyncio.Lock] = {}
        self._collection_lock = asyncio.Lock()
        # watch_id -> (reason, snapshot, note) for an exit order that is in flight
        self._pending_exit_reason: dict[
            str, tuple[ExitReason, Snapshot | None, str]
        ] = {}
        # watch_id -> why a resting entry order was cancelled on purpose, so the
        # cancellation reads as a decision rather than an error when it lands.
        self._cancel_reason: dict[str, str] = {}

        self.halted = False
        self.halt_reason = ""
        # Set when the broker reports market data is not subscribed. Retrying cannot
        # fix that, so it is surfaced once and prominently rather than every tick.
        self.data_api_error = ""
        self._data_error_logged_at: datetime | None = None
        self.started_at = self.now()
        self.last_tick_at: datetime | None = None
        self.last_tick_error: str = ""
        self.tick_count = 0
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------------ setup
    async def start(self) -> None:
        await self.broker.startup()
        for watch in self.store.load_watches():
            self.watches[watch.id] = watch
        if self.watches:
            log.info("engine: restored %d watches from disk", len(self.watches))
            restored = self._restore_simulated_positions()
            await self._reconcile_positions()
            for watch in restored:
                if (
                    watch.position is not None
                    and watch.state is WatchState.IN_POSITION
                    and self._risk(watch).place_stop_at_broker
                ):
                    await self._place_broker_stop(watch)
        self._task = asyncio.create_task(self._run(), name="matheran-engine")

    # ------------------------------------------------------- scoped settings
    # One engine and one set of calculations; only the settings they read are scoped.
    # A watch reads its workspace's strategy and risk (deep copies of the top-level
    # sections until that workspace saves its own); a legacy watch no workspace owns
    # reads the top-level sections, exactly as before.
    def _strategy(self, watch: Watch | None):
        return self.cfg.strategy_for(ws_mod.of_watch(watch) if watch is not None else None)

    def _risk(self, watch: Watch | None):
        return self.cfg.risk_for(ws_mod.of_watch(watch) if watch is not None else None)

    def _restore_simulated_positions(self) -> list[Watch]:
        """Put back the paper positions this process was managing before it stopped.

        Simulated fills live in memory, so without this a restart would read every
        paper position as closed and drop it. A delivery position is carried across
        days; an intraday one only on the day it was opened, since by the next day it
        would have been squared off.
        """
        restore = getattr(self.broker, "restore_position", None)
        if restore is None:
            return []
        today = self.now().date()
        out: list[Watch] = []
        for watch in self.watches.values():
            p = watch.position
            if p is None:
                continue
            if p.product != "DELIVERY" and p.entry_time.date() != today:
                continue
            restore(watch.instrument, p.quantity * p.direction.sign, p.entry_price)
            # The simulated stop order died with the process; it is placed again.
            p.stop_order_id = None
            p.broker_stop_price = None
            out.append(watch)
        if out:
            log.info("engine: restored %d simulated positions", len(out))
        return out

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._persist()
        await self.broker.shutdown()

    async def _reconcile_positions(self) -> None:
        """After a restart, re-attach to anything still open at the broker.

        A restored watch that thinks it is flat while the broker holds stock would
        leave an unmanaged position, so we trust the broker and adopt it.
        """
        try:
            broker_positions = await self.broker.positions()
        except BrokerError as exc:
            log.error("engine: could not read broker positions on startup: %s", exc)
            return

        open_by_key = {
            f"{p.segment}:{p.security_id}": p for p in broker_positions if p.quantity != 0
        }
        # A delivery buy moves from positions into the demat holdings once it settles,
        # so a carried position is looked for there too. Holdings only ever keep an
        # existing delivery position alive; shares bought outside this app are never
        # adopted from them.
        held_by_key: dict = {}
        if any(w.position is not None and w.position.product == "DELIVERY"
               for w in self.watches.values()):
            try:
                held_by_key = {
                    f"{h.segment}:{h.security_id}": h
                    for h in await self.broker.holdings() if h.quantity > 0
                }
            except BrokerError as exc:
                log.error("engine: could not read broker holdings on startup: %s", exc)
        for watch in self.watches.values():
            key = f"{watch.instrument.segment}:{watch.instrument.security_id}"
            live = open_by_key.get(key)
            position = watch.position
            if (
                live is None
                and position is not None
                and position.product == "DELIVERY"
                and position.direction is Direction.LONG
            ):
                held = held_by_key.get(key)
                if held is not None and held.quantity >= position.quantity:
                    watch.notes = "delivery position carried in your holdings"
                    continue
            if live and watch.position is None and live.quantity != 0:
                # The broker's sign tells us which way the open position runs, which
                # may differ from the watch's configured direction after a restart.
                adopted = Direction.LONG if live.quantity > 0 else Direction.SHORT
                watch.direction = adopted
                if watch.ticket is not None and watch.ticket.direction is adopted:
                    # A manual order that filled while this process was down keeps
                    # the stop, trail and target it was placed with.
                    watch.position = self._position_from_fill(
                        watch, abs(live.quantity), live.average_price,
                        watch.entry_order.broker_order_id if watch.entry_order else None,
                    )
                    watch.ticket = None
                else:
                    watch.position = self._plain_position(
                        watch, abs(live.quantity), live.average_price, None, target=False
                    )
                watch.state = WatchState.IN_POSITION
                watch.notes = "adopted an existing broker position on startup"
                log.warning(
                    "engine: adopted open position %s qty=%d avg=%.2f",
                    watch.instrument.symbol,
                    watch.position.quantity,
                    live.average_price,
                )
            elif watch.state in ACTIVE_STATES and not live:
                if await self._entry_still_resting(watch):
                    # A limit entry waiting at the broker is not a position yet, but
                    # forgetting it would leave an order that can still fill unmanaged.
                    watch.notes = "resting entry order re-attached on startup"
                    continue
                watch.state = WatchState.WATCHING
                watch.position = None
                watch.entry_order = None
                watch.exit_order = None
                watch.ticket = None
                watch.notes = "reset on startup: broker reports no open position"

    async def _entry_still_resting(self, watch: Watch) -> bool:
        if watch.state is not WatchState.ENTRY_PLACED or watch.entry_order is None:
            return False
        try:
            state = await self.broker.order_state(watch.entry_order.broker_order_id)
        except BrokerError:
            return False
        return state.status in RESTING_STATUSES

    async def swap_broker(self, new_broker: Broker) -> None:
        """Hot-swap the broker after a credential or mode change.

        Refused while anything is in flight: re-pointing at a different broker
        while an order or position is open would orphan it.
        """
        busy = [w.instrument.symbol for w in self.watches.values() if w.state in ACTIVE_STATES]
        if busy:
            raise EngineError(
                "cannot change broker or mode while orders/positions are open: "
                + ", ".join(busy)
                + ". Exit them first, or halt with square_off."
            )
        for approval in self.pending_approvals():
            self._expire_approval(approval.id, "broker or mode changed")
        for watch in self.watches.values():
            if watch.state is WatchState.PENDING_APPROVAL:
                watch.state = WatchState.WATCHING
                watch.approval_id = None

        old = self.broker
        await new_broker.startup()
        self.broker = new_broker
        self.data_api_error = ""
        self._data_error_logged_at = None
        try:
            await old.shutdown()
        except Exception as exc:  # noqa: BLE001
            log.warning("engine: old broker shutdown complained: %s", exc)
        log.warning(
            "engine: broker swapped to %s (mode=%s, data=%s)",
            new_broker.name,
            self.cfg.mode,
            getattr(new_broker, "data_source", new_broker.name),
        )

    @staticmethod
    def _levels(watch: Watch, reference: float) -> tuple[float, float | None]:
        """Stop and target for a reference price, respecting direction.

        A long risks a fall, so its stop is below and target above; a short is the
        mirror. Keeping this in one place is what stops a sign error from silently
        arming a stop on the wrong side of the entry. A stop or target the watch was
        given as a price is used as it is (see _level_problem for the side check).
        """
        tick = watch.instrument.tick_size
        sign = watch.direction.sign
        if watch.stop_loss_price:
            stop = round_to_tick(float(watch.stop_loss_price), tick)
        else:
            stop = round_to_tick(reference * (1 - sign * watch.stop_loss_pct / 100.0), tick)
        if watch.target_price:
            target = round_to_tick(float(watch.target_price), tick)
        elif watch.target_pct:
            target = round_to_tick(reference * (1 + sign * watch.target_pct / 100.0), tick)
        else:
            target = None
        return stop, target

    @staticmethod
    def _level_problem(
        watch: Watch, reference: float, stop: float, target: float | None
    ) -> str:
        """Why these levels cannot be used for an entry near `reference`, or "".

        Only a level given as a price can be on the wrong side: a % is always measured
        away from the entry. An entry past its own stop would be closed at once, and
        one past its target would be a round trip, so no approval is raised for it.
        """
        sign = watch.direction.sign
        side = "below" if sign > 0 else "above"
        if watch.stop_loss_price and (reference - stop) * sign <= 0:
            return (f"the stop {stop:.2f} is not {side} the price {reference:.2f} for a "
                    f"{watch.direction.value}")
        if watch.target_price and target is not None and (target - reference) * sign <= 0:
            other = "above" if sign > 0 else "below"
            return (f"the target {target:.2f} is not {other} the price {reference:.2f} for a "
                    f"{watch.direction.value}")
        return ""

    @staticmethod
    def _watch_stop(watch: Watch) -> tuple[float, str]:
        """The watch's own stop as (value, unit): a price when it was given one."""
        if watch.stop_loss_price:
            return float(watch.stop_loss_price), "price"
        return float(watch.stop_loss_pct), "pct"

    @staticmethod
    def _watch_target(watch: Watch) -> tuple[float | None, str]:
        """The watch's own target as (value or None, unit)."""
        if watch.target_price:
            return float(watch.target_price), "price"
        return (float(watch.target_pct) if watch.target_pct else None), "pct"

    def _exit_timeframe(self, watch: Watch) -> int:
        """The candles a watch's exit conditions read: its workspace's exit timeframe
        (Strategy tab), else the watch's own timeframe, as before that setting."""
        minutes = self._strategy(watch).exit_timeframe_minutes
        return int(minutes) if minutes else watch.timeframe_minutes

    @staticmethod
    def _ticket_levels(
        instrument: Instrument, default_stop_pct: float, ticket: TradeTicket, reference: float
    ) -> tuple[float, float | None]:
        """Stop and target for a manual order, from its own settings.

        A stop given as a price is used as it is; a percentage is measured from the
        entry. With a trailing distance as well, whichever stop is tighter applies
        from the start - a trail can only ever pull the stop closer. With neither, the
        watch's default percentage applies: no position is opened without a stop.
        """
        tick = instrument.tick_size
        sign = ticket.direction.sign
        stop: float | None = None
        if ticket.sl_value:
            stop = (
                float(ticket.sl_value)
                if ticket.sl_unit == "price"
                else reference * (1 - sign * float(ticket.sl_value) / 100.0)
            )
        if ticket.trail_value and not ticket.trail_trigger_pct:
            # A plain trailing stop follows from the entry. A trailing profit waits for
            # its trigger, so it cannot tighten the opening stop.
            distance = (
                float(ticket.trail_value)
                if ticket.trail_unit == "pts"
                else reference * float(ticket.trail_value) / 100.0
            )
            trail_stop = reference - sign * distance
            if stop is None or (trail_stop - stop) * sign > 0:
                stop = trail_stop
        if stop is None:
            stop = reference * (1 - sign * default_stop_pct / 100.0)
        target: float | None = None
        if ticket.target_value:
            target = (
                float(ticket.target_value)
                if ticket.target_unit == "price"
                else reference * (1 + sign * float(ticket.target_value) / 100.0)
            )
        return round_to_tick(stop, tick), (
            round_to_tick(target, tick) if target is not None else None
        )

    def _position_from_fill(
        self, watch: Watch, quantity: int, fill: float, order_id: str | None
    ) -> Position:
        """A new position, levelled by the watch's pending manual order if it has one."""
        ticket = watch.ticket
        if ticket is None:
            return self._plain_position(watch, quantity, fill, order_id)
        stop, target = self._ticket_levels(watch.instrument, watch.stop_loss_pct, ticket, fill)
        trailing = bool(ticket.trail_value)
        return Position(
            instrument=watch.instrument,
            quantity=quantity,
            direction=watch.direction,
            entry_price=fill,
            entry_time=self.now(),
            stop_price=stop,
            target_price=target,
            entry_order_id=order_id,
            trail_unit=ticket.trail_unit if trailing else None,
            trail_value=float(ticket.trail_value) if trailing else None,
            trail_trigger_pct=ticket.trail_trigger_pct if trailing else None,
            best_price=fill,
            exit_mode=ticket.exit_mode,
            exit_timeframe=ticket.timeframe_minutes,
            product=ticket.product,
        )

    def _plain_position(
        self,
        watch: Watch,
        quantity: int,
        fill: float,
        order_id: str | None,
        *,
        target: bool = True,
    ) -> Position:
        """A position on the watch's own settings: its stop and target %, the Strategy
        tab's trailing profit, and the watch's product and exit mode."""
        stop, target_price = self._levels(watch, fill)
        unit, value, trigger = self._config_trail(watch)
        return Position(
            instrument=watch.instrument,
            quantity=quantity,
            direction=watch.direction,
            entry_price=fill,
            entry_time=self.now(),
            stop_price=stop,
            target_price=target_price if target else None,
            entry_order_id=order_id,
            trail_unit=unit,
            trail_value=value,
            trail_trigger_pct=trigger,
            best_price=fill,
            exit_mode=self.exit_mode_for(watch),
            product=watch.product,
        )

    def _config_trail(self, watch: Watch | None = None) -> tuple[str | None, float | None, float | None]:
        """The Strategy tab's trailing profit as (unit, distance, trigger %), if set."""
        r = self._risk(watch)
        if r.trail_profit_value and r.trail_profit_trigger_pct:
            return r.trail_profit_unit, float(r.trail_profit_value), float(r.trail_profit_trigger_pct)
        return None, None, None

    def exit_mode_for(self, watch: Watch) -> str:
        """How the watch's signalled trades exit: its own setting, else the default."""
        return watch.exit_mode or self._risk(watch).exit_mode

    def _check_trade_settings(
        self, instrument: Instrument, sides: str, product: str, exit_mode: str,
        strategy=None,
    ) -> None:
        """Refuse product and exit combinations that cannot work. `sides` is LONG,
        SHORT or BOTH; `strategy` is the owning workspace's (the top-level by default)."""
        if product not in PRODUCTS:
            raise EngineError("product must be INTRADAY or DELIVERY")
        if exit_mode not in EXIT_MODES:
            raise EngineError("exit mode must be both, sl_target or strategy")
        if product == "DELIVERY" and instrument.segment in CASH_SEGMENTS and sides in {"SHORT", "BOTH"}:
            raise EngineError(
                "a short sale of shares cannot be carried as delivery; use INTRADAY to sell "
                "short, or trade the future or options for a carried short"
            )
        if exit_mode == "strategy" and not effective_rules(strategy or self.cfg.strategy):
            raise EngineError(
                "'exit conditions only' needs at least one exit condition on the Strategy "
                "tab; with none, nothing but a manual exit would close the trade"
            )

    @staticmethod
    def _stop_reason(position: Position) -> ExitReason:
        if position.trailed:
            return ExitReason.TRAILING_PROFIT if position.trail_trigger_pct else ExitReason.TRAILING_STOP
        return ExitReason.STOP_LOSS

    def _lock_for(self, watch_id: str) -> asyncio.Lock:
        if watch_id not in self._watch_locks:
            self._watch_locks[watch_id] = asyncio.Lock()
        return self._watch_locks[watch_id]

    def _persist(self) -> None:
        self.store.save_watches(list(self.watches.values()))

    # ------------------------------------------------- watch administration
    async def add_watch(
        self,
        *,
        instrument: Instrument,
        quantity: int,
        timeframe_minutes: int | None = None,
        stop_loss_pct: float | None = None,
        target_pct: float | None = None,
        stop_loss_price: float | None = None,
        target_price: float | None = None,
        kind: str = "equity",
        direction: Direction | str = Direction.LONG,
        basket_id: str | None = None,
        manual_only: bool = False,
        require_adx: bool | None = None,
        adx_min: float | None = None,
        notes: str = "",
        product: str | None = None,
        exit_mode: str | None = None,
        candle_type: str | None = None,
        workspace: str | None = None,
    ) -> Watch:
        if quantity <= 0:
            raise EngineError("quantity must be a positive number of shares/units")
        if instrument.lot_size > 1 and quantity % instrument.lot_size != 0:
            raise EngineError(
                f"{instrument.symbol} trades in lots of {instrument.lot_size}; "
                f"quantity {quantity} is not a multiple"
            )
        sides = direction.value if isinstance(direction, Direction) else str(direction).upper()
        if sides not in {"LONG", "SHORT", "BOTH"}:
            raise EngineError("direction must be LONG, SHORT or BOTH")
        for name, level in (("stop", stop_loss_price), ("target", target_price)):
            if level is not None and not float(level) > 0:
                raise EngineError(f"a {name} price must be above 0")
        if sides == "BOTH" and (stop_loss_price or target_price):
            raise EngineError(
                "a stop or target given as a price needs a LONG or SHORT watch: one price "
                "cannot sit below a long entry and above a short one. Use % for BOTH."
            )
        try:
            owner = ws_mod.for_new(workspace, instrument, sides, basket_id)
        except ValueError as exc:
            raise EngineError(str(exc)) from None
        # The owner's settings fill whatever the caller left blank; a watch no
        # workspace owns (an old API client trading a future) reads the top level.
        s = self.cfg.strategy_for(owner)
        r = self.cfg.risk_for(owner)
        product = str(
            product or self.cfg.defaults_for(owner).get("product")
            or self.cfg.engine.default_product
        ).upper()
        exit_mode = str(exit_mode or "").lower()
        self._check_trade_settings(
            instrument, sides, product, exit_mode or r.exit_mode, strategy=s
        )

        watch = Watch(
            id=new_id("w"),
            instrument=instrument,
            quantity=int(quantity),
            timeframe_minutes=int(timeframe_minutes or s.timeframe_minutes),
            stop_loss_pct=float(
                stop_loss_pct if stop_loss_pct is not None else r.stop_loss_pct
            ),
            # A target given as a price replaces the % one; the stop % stays as the
            # fallback the charts page and the tickets read.
            target_pct=(None if target_price else
                        target_pct if target_pct is not None else r.target_pct),
            stop_loss_price=float(stop_loss_price) if stop_loss_price else None,
            target_price=float(target_price) if target_price else None,
            kind=kind,
            # A two-way watch starts out long; it flips to whichever side signals.
            direction=Direction.SHORT if sides == "SHORT" else Direction.LONG,
            sides=sides,
            candle_type=normalize_candle_type(candle_type or s.entry_candle_type),
            manual_only=bool(manual_only),
            require_adx=bool(require_adx if require_adx is not None else s.require_adx),
            adx_min=adx_min if adx_min is not None else s.adx_min,
            trade_day=self.now().date().isoformat(),
            notes=notes,
            basket_id=basket_id,
            product=product,
            exit_mode=exit_mode,
            workspace=owner,
        )
        if watch.timeframe_minutes not in WATCH_TIMEFRAMES:
            raise EngineError(
                "timeframe_minutes must be one of "
                + ", ".join(f"{m} ({code_of(m)})" for m in WATCH_TIMEFRAMES)
            )

        async with self._collection_lock:
            duplicate = next(
                (
                    w
                    for w in self.watches.values()
                    if w.instrument.security_id == instrument.security_id
                    and w.instrument.segment == instrument.segment
                    and w.state is not WatchState.DONE
                ),
                None,
            )
            if duplicate is not None:
                # One watch per instrument across every workspace: the broker holds one
                # position per contract, so two owners could not both be right.
                raise EngineError(
                    f"{instrument.symbol} is already being watched (watch {duplicate.id}, "
                    f"{ws_mod.label_of(ws_mod.of_watch(duplicate))})"
                )
            self.watches[watch.id] = watch
            self._persist()

        log.info(
            "engine: watching %s %s qty=%d tf=%s sl=%s %s exit=%s%s",
            instrument.symbol,
            watch.sides,
            watch.quantity,
            code_of(watch.timeframe_minutes),
            f"{watch.stop_loss_price:.2f}" if watch.stop_loss_price else f"{watch.stop_loss_pct:.2f}%",
            watch.product,
            self.exit_mode_for(watch),
            " (manual entries only)" if watch.manual_only else "",
        )
        return watch

    @staticmethod
    def sides_of(watch: Watch) -> list[Direction]:
        """The directions a watch is allowed to trade."""
        if watch.sides == "BOTH":
            return [Direction.LONG, Direction.SHORT]
        if watch.sides in {"LONG", "SHORT"}:
            return [Direction(watch.sides)]
        return [watch.direction]

    def _entry_signal(
        self, watch: Watch, ind: Indicators, ltp: float | None
    ) -> tuple[SignalResult, Direction]:
        """Evaluate the entry gate on every side the watch trades.

        For a two-way watch the long conditions and their mirror image are mutually
        exclusive - price cannot be above and below VWAP at once, and RSI cannot cross
        its signal line both ways on one bar - so at most one side is ever ready. When
        neither is, the side price currently favours is reported, being the one
        closer to firing.
        """
        results: list[tuple[SignalResult, Direction]] = []
        for side in self.sides_of(watch):
            signal = evaluate_entry(
                ind,
                self._strategy(watch),
                ltp=ltp,
                require_adx=watch.require_adx,
                adx_min=watch.adx_min,
                direction=side,
            )
            if signal.ready:
                return signal, side
            results.append((signal, side))
        if len(results) > 1:
            for signal, side in results:
                vwap_ok = "price_below_vwap" if side is Direction.SHORT else "price_above_vwap"
                if signal.checks.get(vwap_ok):
                    return signal, side
        return results[0]

    async def remove_watch(self, watch_id: str, *, force: bool = False) -> None:
        watch = self.watches.get(watch_id)
        if watch is None:
            raise EngineError(f"no such watch: {watch_id}")
        if watch.position is not None and not force:
            raise EngineError(
                "this watch holds an open position; exit it first or pass force=true "
                "(force leaves the position unmanaged)"
            )
        if not force and watch.state in {WatchState.ENTRY_PLACED, WatchState.EXIT_PLACED}:
            # Forgetting a resting order would leave it able to fill with nobody
            # managing the result.
            raise EngineError(
                "an order for this watch is still working at the broker; cancel it or "
                "let it complete first"
            )
        async with self._collection_lock:
            self.watches.pop(watch_id, None)
            self._watch_locks.pop(watch_id, None)
            if watch.approval_id:
                self._expire_approval(watch.approval_id, "watch removed")
            self._persist()

    def set_paused(self, watch_id: str, paused: bool) -> Watch:
        watch = self.watches.get(watch_id)
        if watch is None:
            raise EngineError(f"no such watch: {watch_id}")
        if paused:
            if watch.state in ACTIVE_STATES:
                raise EngineError("cannot pause a watch that has a live order or position")
            if watch.state is WatchState.GTT_PENDING:
                raise EngineError("a GTT order is waiting on this watch; cancel it before pausing")
            watch.state = WatchState.PAUSED
        elif watch.state is WatchState.PAUSED:
            watch.state = WatchState.WATCHING
        watch.touch()
        self._persist()
        return watch

    # ------------------------------------------------------------ approvals
    def pending_approvals(self) -> list[Approval]:
        return [a for a in self.approvals.values() if a.status == "pending"]

    def _expire_approval(self, approval_id: str, reason: str) -> None:
        approval = self.approvals.get(approval_id)
        if approval and approval.status == "pending":
            approval.status = "expired"
            approval.decided_at = self.now()
            approval.note = reason

    async def approve(self, approval_id: str) -> dict:
        approval = self.approvals.get(approval_id)
        if approval is None:
            raise EngineError(f"no such approval: {approval_id}")
        if approval.status != "pending":
            raise EngineError(f"approval is already {approval.status}")
        if self.now() > approval.expires_at:
            self._expire_approval(approval_id, "expired before it was approved")
            watch = self.watches.get(approval.watch_id)
            if watch and watch.state is WatchState.PENDING_APPROVAL:
                watch.state = WatchState.WATCHING
                watch.approval_id = None
            raise EngineError("approval expired; wait for the next signal")
        if self.halted:
            raise EngineError(f"engine is halted: {self.halt_reason}")

        watch = self.watches.get(approval.watch_id)
        if watch is None:
            raise EngineError("the watch behind this approval no longer exists")

        async with self._lock_for(watch.id):
            if watch.position is not None or watch.state in ACTIVE_STATES:
                raise EngineError("this watch already has an order or position in flight")
            approval.status = "approved"
            approval.decided_at = self.now()
            # The approval is what the operator read, so it decides the side.
            watch.direction = approval.direction
            try:
                await self._place_entry(watch, approval)
            except BrokerError as exc:
                watch.state = WatchState.WATCHING
                watch.approval_id = None
                watch.last_error = str(exc)
                watch.cooldown_until = self.now() + timedelta(
                    seconds=self.cfg.engine.cooldown_seconds
                )
                self._persist()
                raise EngineError(f"order placement failed: {exc}") from exc
            self._persist()

        return {
            "approval": approval.as_dict(),
            "watch": watch.as_dict(),
            "mode": self.cfg.mode,
        }

    async def reject(self, approval_id: str, note: str = "") -> dict:
        approval = self.approvals.get(approval_id)
        if approval is None:
            raise EngineError(f"no such approval: {approval_id}")
        if approval.status != "pending":
            raise EngineError(f"approval is already {approval.status}")
        approval.status = "rejected"
        approval.decided_at = self.now()
        approval.note = note or "rejected"

        watch = self.watches.get(approval.watch_id)
        if watch is not None:
            watch.state = WatchState.WATCHING
            watch.approval_id = None
            watch.cooldown_until = self.now() + timedelta(
                seconds=self.cfg.engine.cooldown_seconds
            )
            watch.touch()
            self._persist()
        return {"approval": approval.as_dict()}

    # --------------------------------------------------------------- control
    async def halt(self, square_off: bool = False, reason: str = "manual halt") -> dict:
        self.halted = True
        self.halt_reason = reason
        log.warning("engine: HALTED (%s), square_off=%s", reason, square_off)

        for approval in self.pending_approvals():
            self._expire_approval(approval.id, "engine halted")
        for watch in self.watches.values():
            if watch.state is WatchState.PENDING_APPROVAL:
                watch.state = WatchState.WATCHING
                watch.approval_id = None

        # A resting limit entry could still fill after the halt and open a position
        # nobody asked for any more, so it is pulled. A pending GTT stays: it lives in
        # this process and cannot fire while halted.
        cancelled = []
        for watch in list(self.watches.values()):
            order = watch.entry_order
            if (
                watch.state is WatchState.ENTRY_PLACED
                and order is not None
                and order.order_type is OrderType.LIMIT
            ):
                async with self._lock_for(watch.id):
                    try:
                        if await self._cancel_resting_entry(watch, "engine halted"):
                            cancelled.append(watch.id)
                    except BrokerError as exc:
                        watch.last_error = f"halt could not cancel the resting entry: {exc}"
                        log.error("engine: %s (%s)", watch.last_error, watch.id)

        exited = []
        if square_off:
            for watch in list(self.watches.values()):
                if watch.position is not None and watch.state is WatchState.IN_POSITION:
                    async with self._lock_for(watch.id):
                        try:
                            await self._place_exit(watch, ExitReason.HALT, None)
                            exited.append(watch.id)
                        except BrokerError as exc:
                            watch.last_error = f"halt square-off failed: {exc}"
                            log.error("engine: halt square-off failed for %s: %s", watch.id, exc)
        self._persist()
        return {
            "halted": True,
            "reason": reason,
            "squared_off": exited,
            "cancelled_orders": cancelled,
        }

    def resume(self) -> dict:
        self.halted = False
        self.halt_reason = ""
        log.info("engine: resumed")
        return {"halted": False}

    def status(self) -> dict:
        open_positions = sum(1 for w in self.watches.values() if w.position is not None)
        return {
            "mode": self.cfg.mode,
            "broker": self.broker.name,
            "data_source": getattr(self.broker, "data_source", self.broker.name),
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "data_api_error": self.data_api_error,
            "watches": len(self.watches),
            "open_positions": open_positions,
            "pending_approvals": len(self.pending_approvals()),
            "started_at": self.started_at.isoformat(),
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_tick_error": self.last_tick_error,
            "ticks": self.tick_count,
            "market_open_now": self._market_open(),
            "now": self.now().isoformat(),
        }

    # ------------------------------------------------------------- main loop
    async def _run(self) -> None:
        interval = max(3, int(self.cfg.engine.poll_seconds))
        while not self._stopping.is_set():
            try:
                await self.tick()
                self.last_tick_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_tick_error = str(exc)
                log.exception("engine: tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    async def tick(self) -> None:
        self.tick_count += 1
        self.last_tick_at = self.now()
        today = self.now().date()

        for watch in self.watches.values():
            if watch.trade_day != today.isoformat():
                watch.trade_day = today.isoformat()
                watch.trades_today = 0
                if watch.state is WatchState.DONE:
                    watch.state = WatchState.WATCHING

        self._expire_stale_approvals()

        watches = [w for w in self.watches.values() if w.state is not WatchState.PAUSED]
        if not watches:
            return

        prices = await self._fetch_prices(watches)

        for watch in watches:
            try:
                async with self._lock_for(watch.id):
                    await self._tick_watch(watch, prices.get(watch.instrument.security_id), today)
            except BrokerError as exc:
                watch.last_error = str(exc)
                self._note_data_error(exc, f"candles for {watch.instrument.symbol}")
            except Exception as exc:  # noqa: BLE001
                watch.last_error = str(exc)
                log.exception("engine: %s tick failed", watch.instrument.symbol)

        self._persist()

    async def _fetch_prices(self, watches: list[Watch]) -> dict[str, float]:
        unique: dict[str, Instrument] = {}
        for w in watches:
            unique.setdefault(w.instrument.security_id, w.instrument)
        try:
            prices = await self.broker.ltp(list(unique.values()))
        except BrokerError as exc:
            self._note_data_error(exc, "quotes")
            return {}
        self.data_api_error = ""  # a successful fetch clears the sticky warning
        # A zero or negative quote is missing data, not a real price. Dropping it
        # lets the strategy fall back to the last closed candle instead of
        # silently comparing everything against 0.
        return {sid: price for sid, price in prices.items() if price and price > 0}

    DATA_BLOCKED_CODES = {"806", "DH-902", "807", "808", "809", "DH-901"}

    def _note_data_error(self, exc: BrokerError, what: str) -> None:
        """Record an unfixable market-data failure without flooding the log.

        A missing Data API subscription or an expired token will not resolve on
        retry, so it is logged at most once every five minutes and shown in the UI.
        """
        if exc.code in self.DATA_BLOCKED_CODES:
            self.data_api_error = str(exc)
            now = self.now()
            if (
                self._data_error_logged_at is None
                or (now - self._data_error_logged_at).total_seconds() > 300
            ):
                self._data_error_logged_at = now
                log.error("engine: market data unavailable (%s): %s", what, exc)
            return
        log.warning("engine: %s fetch failed: %s", what, exc)

    def _expire_stale_approvals(self) -> None:
        now = self.now()
        for approval in list(self.approvals.values()):
            if approval.status == "pending" and now > approval.expires_at:
                self._expire_approval(approval.id, "not approved in time")
                watch = self.watches.get(approval.watch_id)
                if watch and watch.state is WatchState.PENDING_APPROVAL:
                    watch.state = WatchState.WATCHING
                    watch.approval_id = None
                    watch.touch()

    async def _tick_watch(self, watch: Watch, ltp: float | None, today: date) -> None:
        state = watch.state
        if state is WatchState.GTT_PENDING:
            await self._check_gtt(watch, ltp)
        elif state is WatchState.ENTRY_PLACED:
            await self._poll_entry(watch)
        elif state is WatchState.EXIT_PLACED:
            await self._poll_exit(watch)
        elif state is WatchState.IN_POSITION:
            await self._manage_position(watch, ltp, today)
        elif state is WatchState.WATCHING:
            await self._look_for_entry(watch, ltp, today)

    # ------------------------------------------------------------ entry path
    def _market_open(self) -> bool:
        now = self.now()
        if now.weekday() >= 5:
            return False
        day = now.date()
        return at(day, self.cfg.engine.market_open) <= now <= at(
            day, self.cfg.engine.market_close
        )

    def _entries_allowed(self, product: str = "INTRADAY") -> tuple[bool, str]:
        """Whether a new entry may go out now. The no-new-entry cutoff exists because
        intraday positions are squared off soon after it, so a delivery entry, which is
        carried, may go out until the close."""
        if self.halted:
            return False, f"engine halted: {self.halt_reason}"
        now = self.now()
        if not self._market_open():
            return False, "outside market hours"
        if product != "DELIVERY" and now >= at(now.date(), self.cfg.engine.no_new_entry_after):
            return False, f"no new intraday entries after {self.cfg.engine.no_new_entry_after}"
        active = sum(1 for w in self.watches.values() if w.state in ACTIVE_STATES)
        if active >= self.cfg.engine.max_open_positions:
            return False, f"max_open_positions ({self.cfg.engine.max_open_positions}) reached"
        return True, ""

    CLOSED_MARKET_REFRESH_SECONDS = 600

    def _snapshot_is_stale(self, watch: Watch) -> bool:
        """Whether to spend a data call refreshing a watch while entries are blocked."""
        if watch.last_signal is None:
            return True
        ts = watch.last_signal.snapshot.candle_ts
        if ts is None:
            return True
        return (self.now() - watch.updated_at).total_seconds() > self.CLOSED_MARKET_REFRESH_SECONDS

    async def _candles(self, watch: Watch, minutes: int, today: date):
        """(closed candles, the candle still forming) for this watch at `minutes`.

        Short timeframes resample the cached 1-minute feed, as the engine always has.
        An hour and up also needs earlier sessions, from the provider's history; enough
        bars are loaded for the indicators to settle, not just to be defined.
        """
        segment = watch.instrument.segment
        if minutes < HISTORY_FROM_MINUTES:
            raw = await self.broker.intraday_candles(watch.instrument, today, 1)
            series = resample(raw, minutes, segment)
        else:
            series = await load_series(
                self.broker, watch.instrument, minutes,
                bars=max(150, 3 * self._strategy(watch).warmup_bars()), now=self.now(),
            )
        return drop_forming(series, minutes, self.now(), segment)

    async def _indicators(self, watch: Watch, today: date) -> Indicators:
        closed, _forming = await self._candles(watch, watch.timeframe_minutes, today)
        return Indicators(apply_candle_type(closed, watch.candle_type), self._strategy(watch))

    async def _look_for_entry(self, watch: Watch, ltp: float | None, today: date) -> None:
        if watch.trades_today >= self.cfg.engine.max_trades_per_day:
            watch.state = WatchState.DONE
            watch.notes = f"hit max_trades_per_day ({self.cfg.engine.max_trades_per_day})"
            return
        if watch.cooldown_until and self.now() < watch.cooldown_until:
            return

        allowed, why = self._entries_allowed(watch.product)
        if allowed and watch.manual_only:
            # A basket leg: it enters together with its basket, never on its own.
            allowed, why = False, "basket leg: enters only when its basket is executed"

        # Indicators are still computed when entries are blocked, so the console shows
        # live VWAP/RSI/Supertrend values instead of a row of dashes. Outside market
        # hours this is throttled, since nothing is changing.
        if not allowed and not self._snapshot_is_stale(watch):
            watch.last_error = ""
            watch.notes = why
            return

        ind = await self._indicators(watch, today)
        signal, side = self._entry_signal(watch, ind, ltp)
        watch.last_signal = signal
        # The console's Ready column reads which side was checked, and when.
        watch.signal_side = side.value
        watch.signal_at = self.now()
        watch.touch()

        if not allowed:
            watch.last_error = ""
            watch.notes = why
            return

        prefix = f"{side.value.lower()}: " if watch.sides == "BOTH" else ""
        watch.notes = prefix + "; ".join(signal.reasons[:3])
        if not signal.ready:
            return

        # A two-way watch trades whichever side signalled; everything downstream
        # (stop side, order sides, exits, P&L) reads the direction from here.
        watch.direction = side
        reference = ltp if ltp is not None else signal.snapshot.close
        if not reference:
            watch.last_error = "signal fired but no price available to size the stop"
            return

        stop_price, target_price = self._levels(watch, reference)
        if self.exit_mode_for(watch) != "strategy":
            problem = self._level_problem(watch, reference, stop_price, target_price)
            if problem:
                watch.notes = f"{prefix}signal, but {problem}: no approval raised"
                return

        approval = Approval(
            id=new_id("appr"),
            watch_id=watch.id,
            direction=watch.direction,
            instrument=watch.instrument,
            quantity=watch.quantity,
            reference_price=round(reference, 2),
            stop_price=stop_price,
            target_price=target_price,
            snapshot=signal.snapshot,
            checks=signal.checks,
            created_at=self.now(),
            expires_at=self.now() + timedelta(seconds=self.cfg.engine.approval_ttl_seconds),
            product=watch.product,
            exit_mode=self.exit_mode_for(watch),
            workspace=ws_mod.of_watch(watch),
        )
        self.approvals[approval.id] = approval
        watch.approval_id = approval.id
        watch.state = WatchState.PENDING_APPROVAL
        watch.touch()
        log.info(
            "engine: APPROVAL NEEDED %s %s qty=%d ref=%.2f stop=%.2f (approval %s)",
            watch.direction.value,
            watch.instrument.symbol,
            watch.quantity,
            reference,
            stop_price,
            approval.id,
        )

    async def _place_entry(
        self,
        watch: Watch,
        approval: Approval,
        *,
        order_type: OrderType = OrderType.MARKET,
        price: float = 0.0,
    ) -> None:
        correlation = f"mth-{watch.id[-8:]}-e{watch.trades_today + 1}"
        quantity = int(approval.quantity or watch.quantity)
        placed = await self.broker.place_order(
            instrument=watch.instrument,
            side=watch.direction.entry_side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            correlation_id=correlation,
            product_type=approval.product,
        )
        watch.entry_order = OrderRef(
            broker_order_id=placed.broker_order_id,
            correlation_id=correlation,
            side=watch.direction.entry_side,
            order_type=order_type,
            quantity=quantity,
            price=float(price or 0.0),
            status=placed.status,
            message=placed.message,
            placed_at=self.now(),
        )
        watch.state = WatchState.ENTRY_PLACED
        watch.approval_id = approval.id
        watch.last_error = ""
        watch.touch()
        log.info(
            "engine: %s entry order %s placed for %s qty=%d%s (%s)",
            order_type.value,
            placed.broker_order_id,
            watch.instrument.symbol,
            quantity,
            f" @ {price:.2f}" if order_type is OrderType.LIMIT else "",
            self.cfg.mode,
        )
        # Read the order straight back: an entry that has already filled becomes a
        # position, with its protective stop at the broker, now rather than one poll
        # interval later.
        try:
            await self._poll_entry(watch)
        except BrokerError as exc:
            log.warning(
                "engine: could not read back entry order %s yet: %s",
                placed.broker_order_id, exc,
            )

    async def _poll_entry(self, watch: Watch, *, allow_cancel: bool = True) -> None:
        order = watch.entry_order
        if order is None:
            watch.state = WatchState.WATCHING
            watch.ticket = None
            return

        state = await self.broker.order_state(order.broker_order_id)
        order.status = state.status
        order.filled_quantity = state.filled_quantity
        order.average_price = state.average_price
        order.message = state.message

        ended = state.status in {OrderStatus.REJECTED, OrderStatus.CANCELLED}
        if state.status is OrderStatus.FILLED or (ended and state.filled_quantity > 0):
            # A cancelled order that part-filled still left a position behind, so the
            # part that filled is managed like any other.
            quantity = state.filled_quantity or order.quantity
            fill = state.average_price or 0.0
            if fill <= 0 and order.order_type is OrderType.LIMIT and order.price > 0:
                fill = order.price
            approval = self.approvals.get(watch.approval_id or "")
            if fill <= 0 and approval:
                fill = approval.reference_price
            self._cancel_reason.pop(watch.id, None)
            await self._open_position(watch, quantity, fill, order)
            return

        if ended:
            why = self._cancel_reason.pop(watch.id, None)
            watch.state = WatchState.WATCHING
            watch.entry_order = None
            watch.ticket = None
            if why:
                watch.last_error = ""
                watch.notes = f"entry order cancelled: {why}"
                log.info("engine: entry order %s cancelled (%s)", order.broker_order_id, why)
                return
            watch.last_error = f"entry order {state.status.value}: {state.message}"
            watch.cooldown_until = self.now() + timedelta(
                seconds=self.cfg.engine.cooldown_seconds
            )
            log.warning("engine: %s", watch.last_error)
            return

        if order.order_type is OrderType.LIMIT:
            # A limit entry rests until the price comes to it, but not past the
            # no-new-entry cutoff: a fill after it would be an entry the rules forbid.
            # A delivery entry is allowed until the close, so it rests until then.
            now = self.now()
            cutoff = (
                self.cfg.engine.market_close
                if self._pending_product(watch) == "DELIVERY"
                else self.cfg.engine.no_new_entry_after
            )
            expired = order.placed_at.date() != now.date() or now >= at(now.date(), cutoff)
            if allow_cancel and expired:
                await self._cancel_resting_entry(
                    watch, f"not filled by the {cutoff} no-new-entry cutoff"
                )
                return
            watch.notes = (
                f"limit {order.side.value} {order.quantity} @ {order.price:.2f} resting "
                "at the broker"
                + (f", {state.filled_quantity} filled so far" if state.filled_quantity else "")
            )
            return

        age = (self.now() - order.placed_at).total_seconds()
        if age > ENTRY_ORDER_TIMEOUT_SECONDS:
            log.warning(
                "engine: entry order %s unfilled after %.0fs, cancelling",
                order.broker_order_id,
                age,
            )
            await self.broker.cancel_order(order.broker_order_id)
            watch.last_error = "entry order timed out and was cancelled"
            watch.state = WatchState.WATCHING
            watch.entry_order = None
            watch.cooldown_until = self.now() + timedelta(
                seconds=self.cfg.engine.cooldown_seconds
            )

    def _pending_product(self, watch: Watch) -> str:
        """The product of the entry order working on this watch."""
        if watch.ticket is not None:
            return watch.ticket.product
        approval = self.approvals.get(watch.approval_id or "")
        return approval.product if approval is not None else watch.product

    async def _cancel_resting_entry(self, watch: Watch, why: str) -> bool:
        """Cancel a working entry order and settle whatever it left behind.

        The order is read back afterwards, because it may have filled - fully or in
        part - before the cancel reached the exchange; a filled part becomes a managed
        position. Returns False when the cancel did not go through.
        """
        order = watch.entry_order
        if order is None:
            return True
        self._cancel_reason[watch.id] = why
        if not await self.broker.cancel_order(order.broker_order_id):
            self._cancel_reason.pop(watch.id, None)
            try:
                await self._poll_entry(watch, allow_cancel=False)
            except BrokerError:
                pass
            if watch.position is not None:
                watch.notes = f"entry filled before it could be cancelled ({why})"
            else:
                watch.last_error = (
                    f"could not cancel the resting entry order {order.broker_order_id} "
                    f"({why}); check your broker terminal"
                )
                log.error("engine: %s", watch.last_error)
            return False
        try:
            await self._poll_entry(watch, allow_cancel=False)
        except BrokerError as exc:
            # Settled on the next tick instead; the cancel itself went through.
            log.warning("engine: could not read back cancelled order %s: %s",
                        order.broker_order_id, exc)
        return True

    async def _open_position(
        self, watch: Watch, quantity: int, fill: float, order: OrderRef
    ) -> None:
        watch.position = self._position_from_fill(
            watch, quantity, fill, order.broker_order_id
        )
        watch.ticket = None
        watch.state = WatchState.IN_POSITION
        watch.touch()
        position = watch.position
        log.info(
            "engine: FILLED %s %s qty=%d @ %.2f | stop %.2f target %s%s",
            watch.direction.value,
            watch.instrument.symbol,
            position.quantity,
            fill,
            position.stop_price,
            f"{position.target_price:.2f}" if position.target_price else "none",
            f" | trailing {position.trail_value:g}{'%' if position.trail_unit == 'pct' else ' pts'}"
            if position.trail_value else "",
        )
        if position.price_exits and position.stop_breached(fill):
            # Only a stop given as a price can land on the wrong side of the fill (a gap,
            # or slippage straight through it). The limit it expresses is already broken.
            watch.last_error = (
                f"filled at {fill:.2f}, already beyond the stop {position.stop_price:.2f}; "
                "closing at market"
            )
            log.warning("engine: %s (%s)", watch.last_error, watch.instrument.symbol)
            try:
                await self._place_exit(watch, ExitReason.STOP_LOSS, None, note=watch.last_error)
            except BrokerError as exc:
                log.error("engine: immediate stop exit failed for %s: %s", watch.id, exc)
            return
        if self._risk(watch).place_stop_at_broker:
            await self._place_broker_stop(watch)

    async def _place_broker_stop(self, watch: Watch) -> None:
        """Resting SL-M at the broker so the stop survives this process dying.

        Not for a position that exits on its conditions only: it has no stop. Placed
        with the position's own product, since a stop on the wrong product would open
        a new position instead of closing this one.
        """
        position = watch.position
        if position is None or not position.price_exits:
            return
        try:
            placed = await self.broker.place_order(
                instrument=watch.instrument,
                side=watch.direction.exit_side,
                quantity=position.quantity,
                order_type=OrderType.STOP_LOSS_MARKET,
                trigger_price=position.stop_price,
                correlation_id=f"mth-{watch.id[-8:]}-sl",
                product_type=position.product,
            )
            position.stop_order_id = placed.broker_order_id
            position.broker_stop_price = position.stop_price
            log.info(
                "engine: broker stop %s resting at %.2f for %s",
                placed.broker_order_id,
                position.stop_price,
                watch.instrument.symbol,
            )
        except BrokerError as exc:
            watch.last_error = (
                f"could not place the protective stop at the broker ({exc}); "
                "the engine will enforce the stop on price instead"
            )
            log.error("engine: %s", watch.last_error)

    # --------------------------------------------------------- position path
    async def _manage_position(self, watch: Watch, ltp: float | None, today: date) -> None:
        position = watch.position
        if position is None:
            watch.state = WatchState.WATCHING
            return

        # Did the resting broker stop already execute?
        if position.stop_order_id:
            try:
                stop_state = await self.broker.order_state(position.stop_order_id)
            except BrokerError:
                stop_state = None
            if stop_state and stop_state.status is OrderStatus.FILLED:
                exit_price = (
                    stop_state.average_price or position.broker_stop_price or position.stop_price
                )
                self._book_trade(watch, exit_price, self._stop_reason(position), None,
                                 note=f"resting stop order filled at {exit_price:.2f}")
                return
            if stop_state and stop_state.status in {OrderStatus.CANCELLED, OrderStatus.REJECTED}:
                # A day order lapses at the close, so a delivery position carried
                # overnight needs its stop placed again; one cancelled at the broker
                # terminal is put back too, since the engine still holds the position.
                log.warning("engine: resting stop %s for %s is %s; placing it again",
                            position.stop_order_id, watch.instrument.symbol,
                            stop_state.status.value)
                position.stop_order_id = None
                position.broker_stop_price = None
                if self._market_open() and self._risk(watch).place_stop_at_broker:
                    await self._place_broker_stop(watch)

        now = self.now()
        if position.product != "DELIVERY" and now >= at(now.date(), self.cfg.engine.square_off_time):
            await self._place_exit(watch, ExitReason.SQUARE_OFF, None,
                                   note=f"square-off at {self.cfg.engine.square_off_time}")
            return

        if position.product == "DELIVERY" and not self._market_open():
            # Carried overnight. Exits resume at the open; an order sent now would be
            # refused, and resent on every tick.
            if position.price_exits and position.stop_order_id is None and self._risk(watch).place_stop_at_broker:
                watch.notes = "delivery: market closed; the stop is placed again at the open"
            else:
                watch.notes = "delivery: market closed; exits resume at the open"
            return

        if ltp is not None and position.price_exits:
            await self._maybe_move_stop_to_breakeven(watch, ltp)
            await self._maybe_trail_stop(watch, ltp)
            if watch.position is None:
                return  # the old broker stop turned out to have filled while moving it
            if position.stop_breached(ltp):
                log.warning(
                    "engine: stop breached on price for %s (ltp %.2f, stop %.2f)",
                    watch.instrument.symbol,
                    ltp,
                    position.stop_price,
                )
                kind = "trailing stop" if position.trailed else "stop"
                await self._place_exit(
                    watch, self._stop_reason(position), None,
                    note=f"LTP {ltp:.2f} reached the {kind} {position.stop_price:.2f}",
                )
                return
            if position.target_reached(ltp):
                await self._place_exit(
                    watch, ExitReason.TARGET, None,
                    note=f"LTP {ltp:.2f} reached the target {position.target_price:.2f}",
                )
                return

        if (
            position.product == "DELIVERY"
            and position.price_exits
            and position.stop_order_id is None
            and self._risk(watch).place_stop_at_broker
            and position.broker_stop_price is None
            and not watch.last_error
        ):
            # A carried position whose overnight stop lapsed: put it back at the open.
            await self._place_broker_stop(watch)

        if not position.use_exit_rules:
            watch.notes = "holding: stop, target and trailing only (exit conditions off for this trade)"
            return

        outcome, snapshot = await self._exit_rules_outcome(watch, today, ltp)
        watch.notes = outcome.text
        if outcome.fired:
            log.info("engine: exit rule for %s: %s", watch.instrument.symbol, outcome.text)
            await self._place_exit(watch, ExitReason.EXIT_RULE, snapshot, note=outcome.text)

    async def _exit_rules_outcome(
        self, watch: Watch, today: date, ltp: float | None
    ) -> tuple[RulesOutcome, Snapshot | None]:
        """The Strategy tab's exit conditions, on the candles of this watch.

        Candle-close rows see closed candles only, and only those that closed after the
        position opened. Live rows see the forming candle too, priced at LTP.
        """
        strategy = self._strategy(watch)
        rules = effective_rules(strategy)
        if not rules:
            return RulesOutcome(
                False, [], "holding: no exit conditions set; stop, target and square-off only"
            ), None
        position = watch.position
        # A chart order keeps the chart's timeframe; everything else reads the
        # workspace's exit timeframe, at this check (as it reads the rows themselves).
        minutes = (
            position.exit_timeframe
            if position is not None and position.exit_timeframe
            else self._exit_timeframe(watch)
        )
        closed, forming = await self._candles(watch, minutes, today)
        live = live_series(closed, forming, ltp) if needs_live(rules) else None
        outcome = exit_outcome(
            closed,
            strategy,
            watch.direction,
            live=live,
            entry_time=position.entry_time if position is not None else None,
            timeframe_minutes=minutes,
            segment=watch.instrument.segment,
        )
        snapshot = Indicators(closed, strategy).snapshot(ltp) if outcome.fired else None
        return outcome, snapshot

    async def _maybe_trail_stop(self, watch: Watch, ltp: float) -> None:
        """Pull the stop along behind the best price since entry. Never loosens it.

        The engine enforces the exact trailed level on every price check. The resting
        broker order is the backstop for this process dying, so it is moved in steps of
        a quarter of the trail distance rather than on every tick, which would flood
        the broker with order changes.
        """
        position = watch.position
        if position is None or not position.trail_value:
            return
        sign = position.direction.sign
        best = position.best_price if position.best_price is not None else position.entry_price
        if (ltp - best) * sign > 0:
            best = ltp
            position.best_price = best
        if not position.trail_active(best):
            # Trailing profit: nothing moves until the trade is far enough in profit.
            return
        distance = position.trail_distance(best)
        if not distance:
            return
        tick = watch.instrument.tick_size
        candidate = round_to_tick(best - sign * distance, tick)
        if (candidate - position.stop_price) * sign <= 0:
            return
        old = position.stop_price
        position.stop_price = candidate
        position.trailed = True
        log.info(
            "engine: %s %s %.2f -> %.2f (best %.2f)",
            watch.instrument.symbol,
            "trailing profit" if position.trail_trigger_pct else "trailing stop",
            old, candidate, best,
        )
        if not self._risk(watch).place_stop_at_broker:
            return
        step = max(tick, distance * 0.25)
        if (
            position.stop_order_id
            and position.broker_stop_price is not None
            and (candidate - position.broker_stop_price) * sign < step
        ):
            return
        await self._replace_broker_stop(watch)

    async def _replace_broker_stop(self, watch: Watch) -> None:
        """Move the resting broker stop to the position's current stop price.

        The old order is cancelled and, if that fails, read back: when it had already
        filled the position is closed, and placing a second stop on top of it would
        open a reverse position.
        """
        position = watch.position
        if position is None:
            return
        if position.stop_order_id:
            order_id = position.stop_order_id
            if not await self.broker.cancel_order(order_id):
                try:
                    st = await self.broker.order_state(order_id)
                except BrokerError:
                    st = None
                if st is not None and st.status is OrderStatus.FILLED:
                    price = st.average_price or position.broker_stop_price or position.stop_price
                    self._book_trade(watch, price, self._stop_reason(position), None,
                                     note=f"resting stop order filled at {price:.2f}")
                    return
                watch.last_error = (
                    f"could not move the resting stop {order_id} to "
                    f"{position.stop_price:.2f}; the engine enforces the new level on price"
                )
                log.error("engine: %s", watch.last_error)
                return
            position.stop_order_id = None
            position.broker_stop_price = None
        if self._risk(watch).place_stop_at_broker:
            await self._place_broker_stop(watch)

    async def _maybe_move_stop_to_breakeven(self, watch: Watch, ltp: float) -> None:
        """Lift the stop to entry once the trade is far enough in profit.

        Only ever moves the stop up, and re-places the resting broker order so the
        protection stays real rather than living only in this process.
        """
        trigger = self._risk(watch).breakeven_trigger_pct
        position = watch.position
        if not trigger or position is None:
            return
        sign = position.direction.sign
        # "Already protected" means at or beyond entry in the direction of the trade.
        if (position.stop_price - position.entry_price) * sign >= 0:
            return
        if (ltp - position.entry_price) * sign < position.entry_price * trigger / 100.0:
            return

        new_stop = round_to_tick(position.entry_price, watch.instrument.tick_size)
        # Only ever tighten: for a long that means higher, for a short lower.
        if (new_stop - position.stop_price) * sign <= 0:
            return

        old_stop = position.stop_price
        position.stop_price = new_stop
        log.info(
            "engine: %s in profit past %.2f%%, stop moved %.2f -> %.2f (breakeven)",
            watch.instrument.symbol, trigger, old_stop, new_stop,
        )
        await self._replace_broker_stop(watch)

    async def _place_exit(
        self,
        watch: Watch,
        reason: ExitReason,
        snapshot: Snapshot | None,
        *,
        note: str = "",
    ) -> None:
        position = watch.position
        if position is None:
            return

        # Cancel the resting stop first, otherwise filling this exit while the stop
        # is still live would flip us into a short position.
        if position.stop_order_id:
            cancelled = await self.broker.cancel_order(position.stop_order_id)
            if not cancelled:
                try:
                    st = await self.broker.order_state(position.stop_order_id)
                    if st.status is OrderStatus.FILLED:
                        price = st.average_price or position.broker_stop_price or position.stop_price
                        self._book_trade(
                            watch, price, self._stop_reason(position), snapshot,
                            note=f"resting stop order filled at {price:.2f}",
                        )
                        return
                except BrokerError:
                    pass
                watch.last_error = (
                    f"could not cancel the resting stop {position.stop_order_id}; "
                    "check your broker terminal for a stray order"
                )
                log.error("engine: %s", watch.last_error)
            position.stop_order_id = None

        correlation = f"mth-{watch.id[-8:]}-x{watch.trades_today + 1}"
        placed = await self.broker.place_order(
            instrument=watch.instrument,
            side=watch.direction.exit_side,
            quantity=position.quantity,
            order_type=OrderType.MARKET,
            correlation_id=correlation,
            # Closed with the product it was opened with, or the broker would open a
            # second position instead.
            product_type=position.product,
        )
        watch.exit_order = OrderRef(
            broker_order_id=placed.broker_order_id,
            correlation_id=correlation,
            side=watch.direction.exit_side,
            order_type=OrderType.MARKET,
            quantity=position.quantity,
            status=placed.status,
            message=f"{reason.value}: {placed.message}",
            placed_at=self.now(),
        )
        watch.state = WatchState.EXIT_PLACED
        watch.notes = f"exiting: {reason.value}" + (f" - {note}" if note else "")
        watch.touch()
        self._pending_exit_reason[watch.id] = (reason, snapshot, note)
        # As with entries: book an exit that has already filled straight away.
        try:
            await self._poll_exit(watch)
        except BrokerError as exc:
            log.warning("engine: could not read back exit order %s yet: %s",
                        placed.broker_order_id, exc)

    async def _poll_exit(self, watch: Watch) -> None:
        order = watch.exit_order
        position = watch.position
        if order is None or position is None:
            watch.state = WatchState.WATCHING
            watch.exit_order = None
            return

        state = await self.broker.order_state(order.broker_order_id)
        order.status = state.status
        order.filled_quantity = state.filled_quantity
        order.average_price = state.average_price

        if state.status is OrderStatus.FILLED:
            reason, snapshot, note = self._pending_exit_reason.pop(
                watch.id, (ExitReason.MANUAL, None, "")
            )
            self._book_trade(watch, state.average_price or 0.0, reason, snapshot, note=note)
            return

        if state.status in {OrderStatus.REJECTED, OrderStatus.CANCELLED}:
            watch.last_error = (
                f"exit order {state.status.value} - position is still open, retrying next tick"
            )
            log.error("engine: %s (%s)", watch.last_error, watch.instrument.symbol)
            watch.exit_order = None
            watch.state = WatchState.IN_POSITION
            return

        age = (self.now() - order.placed_at).total_seconds()
        if age > ENTRY_ORDER_TIMEOUT_SECONDS:
            log.error(
                "engine: exit order %s still unfilled after %.0fs on %s",
                order.broker_order_id,
                age,
                watch.instrument.symbol,
            )
            watch.last_error = "exit order is taking unusually long; check your broker terminal"

    def _book_trade(
        self,
        watch: Watch,
        exit_price: float,
        reason: ExitReason,
        snapshot: Snapshot | None,
        *,
        note: str = "",
    ) -> None:
        position = watch.position
        if position is None:
            return
        if exit_price <= 0:
            exit_price = position.entry_price

        trade = Trade(
            id=new_id("t"),
            watch_id=watch.id,
            instrument=watch.instrument,
            quantity=position.quantity,
            entry_price=position.entry_price,
            entry_time=position.entry_time,
            exit_price=round(exit_price, 2),
            exit_time=self.now(),
            exit_reason=reason,
            mode=self.cfg.mode,
            direction=position.direction,
            entry_snapshot=(
                self.approvals[watch.approval_id].snapshot
                if watch.approval_id and watch.approval_id in self.approvals
                else None
            ),
            exit_snapshot=snapshot,
            exit_note=note,
            product=position.product,
            # The owning workspace, so the row stays in its journal whatever happens to
            # the watch later; "legacy" for an old watch no workspace owns.
            workspace=ws_mod.of_watch(watch),
        )
        self.store.append_trade(trade)

        watch.position = None
        watch.entry_order = None
        watch.exit_order = None
        watch.approval_id = None
        watch.ticket = None
        watch.trades_today += 1
        watch.cooldown_until = self.now() + timedelta(seconds=self.cfg.engine.cooldown_seconds)
        watch.state = (
            WatchState.DONE
            if watch.trades_today >= self.cfg.engine.max_trades_per_day
            else WatchState.WATCHING
        )
        watch.notes = f"closed: {reason.value}, pnl {trade.pnl:+.2f}"
        watch.touch()
        log.info(
            "engine: CLOSED %s qty=%d entry %.2f exit %.2f reason=%s pnl=%+.2f",
            watch.instrument.symbol,
            trade.quantity,
            trade.entry_price,
            trade.exit_price,
            reason.value,
            trade.pnl,
        )

    async def enter_now(
        self,
        watch_id: str,
        *,
        note: str = "manual entry",
        direction: Direction | str | None = None,
        order_type: str = "MARKET",
        limit_price: float | None = None,
        product: str | None = None,
        exit_mode: str | None = None,
        sl_value: float | None = None,
        sl_unit: str | None = None,
        target_value: float | None = None,
        target_unit: str | None = None,
        target_given: bool = False,
    ) -> dict:
        """Enter immediately, skipping the signal.

        A one-way watch enters in its own direction. A two-way watch needs to be told
        which: BUY (LONG) or SELL (SHORT). This replaces the signal, not the safety
        rails: halt, market hours, the no-new-entry cutoff, concurrent-position and
        per-day caps all still apply. The operator pressing the button is the
        deliberate decision.

        `order_type` MARKET goes out at market; LIMIT rests at `limit_price` until the
        price comes to it, and is cancelled at the no-new-entry cutoff (intraday) or the
        close (delivery) if still unfilled. `product` (INTRADAY / DELIVERY) and
        `exit_mode` (both / sl_target / strategy) default to the watch's own.

        The stop and target are the watch's own (a % measured from the fill, or a
        price), unless this order gives its own: `sl_value` with `sl_unit` "pct" or
        "price"; `target_value` with `target_unit`, where `target_given` with no value
        means no target for this order. Both are checked against the entry before
        anything is sent.
        """
        watch = self.watches.get(watch_id)
        if not self._risk(watch).allow_manual_buy:
            raise EngineError("manual entry is disabled (risk.allow_manual_buy)")
        if watch is None:
            raise EngineError(f"no such watch: {watch_id}")
        if watch.position is not None:
            raise EngineError("this watch already holds a position")
        if watch.state in ACTIVE_STATES:
            raise EngineError(f"an order is already in flight ({watch.state.value})")
        if watch.state is WatchState.GTT_PENDING:
            raise EngineError("a GTT order is waiting on this watch; cancel it first")
        if watch.trades_today >= self.cfg.engine.max_trades_per_day:
            raise EngineError(
                f"already took {watch.trades_today} trades today "
                f"(max_trades_per_day={self.cfg.engine.max_trades_per_day})"
            )

        allowed_sides = self.sides_of(watch)
        if direction is None:
            if len(allowed_sides) > 1:
                raise EngineError(
                    "this watch trades both ways; pass direction LONG (buy) or SHORT (sell)"
                )
            wanted = allowed_sides[0]
        else:
            try:
                wanted = (
                    direction if isinstance(direction, Direction)
                    else Direction(str(direction).upper())
                )
            except ValueError as exc:
                raise EngineError("direction must be LONG or SHORT") from exc
            if wanted not in allowed_sides:
                raise EngineError(
                    f"this watch only trades {watch.sides}; it cannot "
                    f"{wanted.entry_side.value.lower()} to open"
                )

        kind = str(order_type or "MARKET").upper()
        if kind not in ENTRY_ORDER_TYPES:
            raise EngineError("order type must be MARKET or LIMIT")
        product = str(product or watch.product).upper()
        mode = str(exit_mode or self.exit_mode_for(watch)).lower()
        self._check_trade_settings(watch.instrument, wanted.value, product, mode,
                                   strategy=self._strategy(watch))
        limit: float | None = None
        if kind == "LIMIT":
            if not limit_price or limit_price <= 0:
                raise EngineError("a limit order needs a limit price")
            limit = round_to_tick(float(limit_price), watch.instrument.tick_size)

        allowed, why = self._entries_allowed(product)
        if not allowed:
            raise EngineError(f"cannot {wanted.entry_side.value.lower()} right now: {why}")

        # A pending approval would otherwise still be approvable after this entry
        # and open a second position on the same watch.
        if watch.approval_id:
            self._expire_approval(watch.approval_id, "superseded by a manual entry")
            watch.approval_id = None
        watch.direction = wanted

        ltp = await self._reference_price(watch.instrument)
        if limit is None and not ltp:
            raise EngineError("no price available to size the stop; refusing to trade blind")
        reference = float(limit if limit is not None else ltp)

        # This order's stop and target, else the watch's own.
        def unit_of(raw: str | None) -> str:
            unit = str(raw or "pct").strip().lower()
            if unit not in {"pct", "price"}:
                raise EngineError("stop and target units must be pct or price")
            return unit

        if sl_value:
            stop_value, stop_unit = float(sl_value), unit_of(sl_unit)
        else:
            stop_value, stop_unit = self._watch_stop(watch)
        if target_given:
            goal_value = float(target_value) if target_value else None
            goal_unit = unit_of(target_unit)
        else:
            goal_value, goal_unit = self._watch_target(watch)

        # The order carries its own exits, so a limit that fills later, or after a
        # restart, still gets the stop, target, trail, product and exit mode chosen now.
        # The exit conditions are the watch's own, so they read its workspace's exit
        # timeframe when they are checked (no timeframe of the order's own). The
        # trailing profit is the watch's workspace's, as for a signalled entry.
        trail_unit, trail_value, trail_trigger = self._config_trail(watch)
        ticket = TradeTicket(
            direction=wanted,
            quantity=watch.quantity,
            order_type=kind,
            limit_price=limit,
            sl_value=stop_value,
            sl_unit=stop_unit,
            trail_value=trail_value,
            trail_unit=trail_unit or "pct",
            trail_trigger_pct=trail_trigger,
            target_value=goal_value,
            target_unit=goal_unit,
            exit_mode=mode,
            product=product,
            timeframe_minutes=None,
            note=note,
        )
        stop_price, target_price = self._ticket_levels(
            watch.instrument, watch.stop_loss_pct, ticket, reference
        )
        if mode != "strategy":
            self._check_ticket_levels(ticket, reference, stop_price, target_price)

        try:
            ind = await self._indicators(watch, self.now().date())
            snapshot = ind.snapshot(ltp or reference)
        except BrokerError:
            snapshot = Snapshot(ltp=ltp)

        approval = self._manual_approval(
            watch,
            quantity=watch.quantity,
            reference=reference,
            stop_price=stop_price,
            target_price=target_price,
            snapshot=snapshot,
            note=note,
            product=product,
            exit_mode=mode,
        )

        async with self._lock_for(watch.id):
            trades_before = watch.trades_today
            watch.ticket = ticket
            try:
                await self._place_entry(
                    watch,
                    approval,
                    order_type=OrderType.LIMIT if limit is not None else OrderType.MARKET,
                    price=limit or 0.0,
                )
            except BrokerError as exc:
                approval.status = "rejected"
                approval.note = f"{note}: {exc}"
                watch.ticket = None
                watch.state = WatchState.WATCHING
                watch.approval_id = None
                watch.last_error = str(exc)
                self._persist()
                raise EngineError(f"order failed: {exc}") from exc
            rejected = (
                watch.entry_order is None
                and watch.position is None
                and watch.trades_today == trades_before
            )
            if not rejected and watch.state is not WatchState.ENTRY_PLACED:
                watch.notes = note
            self._persist()
        if rejected:
            raise EngineError(
                "the broker rejected the order: " + (watch.last_error or "no reason given")
            )

        log.warning(
            "engine: MANUAL %s %s %s qty=%d ref=%.2f %s %s (%s)",
            kind, watch.direction.entry_side.value, watch.instrument.symbol,
            watch.quantity, reference, product, mode, self.cfg.mode,
        )
        return {"watch": watch.as_dict(), "approval": approval.as_dict(), "mode": self.cfg.mode}

    async def exit_now(self, watch_id: str) -> dict:
        watch = self.watches.get(watch_id)
        if watch is None:
            raise EngineError(f"no such watch: {watch_id}")
        if watch.position is None:
            raise EngineError("this watch has no open position")
        async with self._lock_for(watch.id):
            # A second exit while the first is in flight would sell twice and leave
            # the account short, so it is refused rather than sent.
            if watch.state is WatchState.EXIT_PLACED:
                raise EngineError("an exit order is already in flight for this position")
            await self._place_exit(watch, ExitReason.MANUAL, None)
            self._persist()
        return watch.as_dict()

    # ------------------------------------------------------ manual order tickets
    def _manual_approval(
        self,
        watch: Watch,
        *,
        quantity: int,
        reference: float,
        stop_price: float,
        target_price: float | None,
        snapshot: Snapshot,
        note: str,
        checks: dict[str, bool] | None = None,
        product: str = "INTRADAY",
        exit_mode: str = "both",
    ) -> Approval:
        """An already-approved record for an entry the operator asked for directly,
        so every entry, signalled or not, leaves the same audit trail."""
        now = self.now()
        approval = Approval(
            product=product,
            exit_mode=exit_mode,
            id=new_id("appr"),
            watch_id=watch.id,
            direction=watch.direction,
            instrument=watch.instrument,
            quantity=quantity,
            reference_price=round(reference, 2),
            stop_price=stop_price,
            target_price=target_price,
            snapshot=snapshot,
            checks=checks or {"manual_override": True},
            created_at=now,
            expires_at=now + timedelta(seconds=self.cfg.engine.approval_ttl_seconds),
            status="approved",
            decided_at=now,
            note=note,
            workspace=ws_mod.of_watch(watch),
        )
        self.approvals[approval.id] = approval
        return approval

    def _watch_for(self, instrument: Instrument) -> Watch | None:
        """The watch on this contract, in whatever state; a finished one last."""
        matches = [
            w for w in self.watches.values()
            if w.instrument.security_id == instrument.security_id
            and w.instrument.segment == instrument.segment
        ]
        matches.sort(key=lambda w: w.state is WatchState.DONE)
        return matches[0] if matches else None

    @staticmethod
    def _check_ticket_levels(
        ticket: TradeTicket, reference: float, stop: float, target: float | None
    ) -> None:
        sign = ticket.direction.sign
        side = ticket.direction.entry_side.value
        if stop <= 0:
            raise EngineError(f"stop {stop:.2f} is not a usable price")
        if (reference - stop) * sign <= 0:
            raise EngineError(
                f"stop {stop:.2f} must be {'below' if sign > 0 else 'above'} the entry "
                f"price {reference:.2f} for a {side}"
            )
        if target is not None and (target - reference) * sign <= 0:
            raise EngineError(
                f"target {target:.2f} must be {'above' if sign > 0 else 'below'} the entry "
                f"price {reference:.2f} for a {side}"
            )

    async def _reference_price(self, instrument: Instrument) -> float | None:
        """Live price, or the last 1-minute close when no quote comes back."""
        prices = await self.broker.ltp([instrument])
        ltp = prices.get(instrument.security_id)
        if ltp and ltp > 0:
            return float(ltp)
        try:
            raw = await self.broker.intraday_candles(instrument, self.now().date(), 1)
        except BrokerError:
            return None
        return float(raw.last.close) if raw and raw.last else None

    @staticmethod
    def _gtt_note(ticket: TradeTicket, ltp: float | None) -> str:
        cmp = "≥" if ticket.trigger_above else "≤"
        then = f"limit {ticket.limit_price:.2f}" if ticket.limit_price else "market"
        now = f" (LTP {ltp:.2f})" if ltp else ""
        return (
            f"GTT {ticket.direction.entry_side.value} {ticket.quantity} waiting for LTP "
            f"{cmp} {ticket.trigger_price:.2f}, then {then}{now}"
        )

    async def place_ticket(
        self,
        *,
        instrument: Instrument,
        ticket: TradeTicket,
        timeframe_minutes: int = 5,
        kind: str = "equity",
        chart_symbol: str = "",
        workspace: str | None = None,
    ) -> dict:
        """A manual order from the charts page: market, limit, or a GTT held here.

        The order's own stop, trailing stop and target replace the watch defaults for
        this one trade, and it can opt out of the Strategy tab's exit rules. Every rail
        the manual Buy button has still applies: halt, market hours and the
        no-new-entry cutoff (for a GTT, checked when it fires), and the position and
        per-day caps. An instrument without a watch gets one that never raises
        approvals of its own, owned by `workspace` (the chart it was placed from).
        """
        try:
            requested = ws_mod.normalize(workspace)
        except ValueError as exc:
            raise EngineError(str(exc)) from None
        existing = self._watch_for(instrument)
        if existing is not None and requested and ws_mod.of_watch(existing) != requested:
            # Trading another workspace's watch from here would move its position and
            # journal rows under this workspace's settings.
            raise EngineError(
                f"{instrument.symbol} is watched in "
                f"{ws_mod.label_of(ws_mod.of_watch(existing))} (watch {existing.id}); trade "
                "it there, or remove that watch first"
            )
        owner = requested or (
            ws_mod.of_watch(existing) if existing is not None
            else ws_mod.for_new(None, instrument, ticket.direction.value)
        )
        risk = self.cfg.risk_for(owner)
        if not risk.allow_manual_buy:
            raise EngineError("manual orders are disabled (risk.allow_manual_buy)")
        if self.halted:
            raise EngineError(f"engine is halted: {self.halt_reason}")
        order_type = str(ticket.order_type).upper()
        if order_type not in TICKET_ORDER_TYPES:
            raise EngineError("order type must be MARKET, LIMIT or GTT")
        ticket.order_type = order_type
        side = ticket.direction.entry_side.value
        lot = max(1, int(instrument.lot_size or 1))
        if ticket.quantity <= 0:
            raise EngineError("quantity must be positive")
        if lot > 1 and ticket.quantity % lot:
            raise EngineError(
                f"{instrument.symbol} trades in lots of {lot}; quantity {ticket.quantity} "
                "is not a multiple"
            )
        if timeframe_minutes not in WATCH_TIMEFRAMES:
            raise EngineError(
                "timeframe must be one of " + ", ".join(code_of(m) for m in WATCH_TIMEFRAMES)
            )
        if (
            ticket.sl_unit not in SL_UNITS
            or ticket.trail_unit not in TRAIL_UNITS
            or ticket.target_unit not in TARGET_UNITS
        ):
            raise EngineError(
                "units: stop loss pct|price, trailing stop pct|pts, target pct|price"
            )
        for label, value, unit in (
            ("stop loss", ticket.sl_value, ticket.sl_unit),
            ("trailing stop", ticket.trail_value, ticket.trail_unit),
            ("target", ticket.target_value, ticket.target_unit),
        ):
            if value is not None and value <= 0:
                raise EngineError(f"{label} must be positive, or left blank")
            if value is not None and unit == "pct" and label != "target" and value >= 100:
                raise EngineError(f"{label} of {value:g}% is not a usable distance")
        if ticket.trail_trigger_pct is not None:
            if ticket.trail_trigger_pct <= 0:
                raise EngineError("the trailing profit trigger must be a positive %, or blank")
            if not ticket.trail_value:
                raise EngineError("a trailing profit needs a trailing distance as well")
        ticket.product = str(ticket.product or "INTRADAY").upper()
        ticket.exit_mode = str(ticket.exit_mode or "both").lower()
        self._check_trade_settings(
            instrument, ticket.direction.value, ticket.product, ticket.exit_mode,
            strategy=self.cfg.strategy_for(owner),
        )
        ticket.timeframe_minutes = int(timeframe_minutes)
        tick = instrument.tick_size
        if order_type == "LIMIT":
            if not ticket.limit_price or ticket.limit_price <= 0:
                raise EngineError("a limit order needs a limit price")
            ticket.limit_price = round_to_tick(ticket.limit_price, tick)
            ticket.trigger_price = None
        elif order_type == "GTT":
            if not ticket.trigger_price or ticket.trigger_price <= 0:
                raise EngineError("a GTT order needs a trigger price")
            ticket.trigger_price = round_to_tick(ticket.trigger_price, tick)
            ticket.limit_price = (
                round_to_tick(ticket.limit_price, tick) if ticket.limit_price else None
            )
        else:
            ticket.limit_price = None
            ticket.trigger_price = None

        # Orders that go out now must be allowed now. A GTT is checked when it fires.
        if order_type != "GTT":
            allowed, why = self._entries_allowed(ticket.product)
            if not allowed:
                raise EngineError(f"cannot {side.lower()} right now: {why}")

        ltp = await self._reference_price(instrument)
        if order_type == "MARKET":
            if not ltp:
                raise EngineError("no price available to size the stop; refusing to trade blind")
            reference = ltp
        elif order_type == "LIMIT":
            reference = float(ticket.limit_price)
        else:
            if not ltp:
                raise EngineError("no live price to arm the GTT against")
            ticket.trigger_above = ticket.trigger_price >= ltp
            reference = float(ticket.limit_price or ticket.trigger_price)

        existing = self._watch_for(instrument)
        if existing is not None and requested and ws_mod.of_watch(existing) != requested:
            raise EngineError(
                f"{instrument.symbol} is watched in "
                f"{ws_mod.label_of(ws_mod.of_watch(existing))} (watch {existing.id}); trade "
                "it there, or remove that watch first"
            )
        default_stop = existing.stop_loss_pct if existing else risk.stop_loss_pct
        stop, target = self._ticket_levels(instrument, default_stop, ticket, reference)
        price_exits = ticket.exit_mode != "strategy"
        if price_exits:
            # Exit-conditions-only orders carry no stop or target, so neither is checked.
            self._check_ticket_levels(ticket, reference, stop, target)
        if ticket.trail_value and price_exits:
            distance = (
                float(ticket.trail_value) if ticket.trail_unit == "pts"
                else reference * float(ticket.trail_value) / 100.0
            )
            if distance < 2 * tick:
                raise EngineError(
                    f"trailing distance {distance:.2f} is under two ticks ({2 * tick:g}); it "
                    "would stop out on the first tick against you"
                )

        created = False
        if existing is not None:
            if existing.basket_id:
                raise EngineError(
                    f"{instrument.symbol} is a leg of a basket; trade it from the Baskets tab"
                )
            if existing.position is not None or existing.state in ACTIVE_STATES:
                raise EngineError(
                    f"{instrument.symbol} already has an order or position in flight "
                    f"(watch {existing.id}); manage that one first"
                )
            if existing.state is WatchState.GTT_PENDING:
                raise EngineError(
                    f"a GTT order is already waiting on {instrument.symbol}; cancel it first"
                )
            if existing.trades_today >= self.cfg.engine.max_trades_per_day:
                raise EngineError(
                    f"already took {existing.trades_today} trades on {instrument.symbol} "
                    f"today (max_trades_per_day={self.cfg.engine.max_trades_per_day})"
                )
            watch = existing
        else:
            watch = await self.add_watch(
                instrument=instrument,
                quantity=ticket.quantity,
                timeframe_minutes=timeframe_minutes,
                kind=kind,
                direction=ticket.direction,
                manual_only=True,
                notes="manual order from the charts page",
                product=ticket.product,
                workspace=requested,
            )
            created = True

        failed: EngineError | None = None
        async with self._lock_for(watch.id):
            if watch.approval_id:
                # Otherwise it could still be approved and open a second position.
                self._expire_approval(watch.approval_id, "superseded by a manual order")
                watch.approval_id = None
            watch.direction = ticket.direction
            watch.ticket = ticket
            if chart_symbol:
                watch.chart_symbol = chart_symbol
            watch.last_error = ""
            if order_type == "GTT":
                watch.state = WatchState.GTT_PENDING
                watch.notes = self._gtt_note(ticket, ltp)
                watch.touch()
            else:
                trades_before = watch.trades_today
                approval = self._manual_approval(
                    watch,
                    quantity=ticket.quantity,
                    reference=reference,
                    stop_price=stop,
                    target_price=target,
                    snapshot=Snapshot(ltp=ltp),
                    note=ticket.note or "manual order from the charts page",
                    checks={"manual_override": True, "chart_ticket": True},
                    product=ticket.product,
                    exit_mode=ticket.exit_mode,
                )
                try:
                    await self._place_entry(
                        watch,
                        approval,
                        order_type=OrderType.LIMIT if order_type == "LIMIT" else OrderType.MARKET,
                        price=ticket.limit_price or 0.0,
                    )
                except BrokerError as exc:
                    approval.status = "rejected"
                    approval.note = f"{approval.note}: {exc}"
                    watch.ticket = None
                    watch.state = WatchState.WATCHING
                    watch.approval_id = None
                    watch.last_error = str(exc)
                    failed = EngineError(f"order failed: {exc}")
                else:
                    rejected = (
                        watch.entry_order is None
                        and watch.position is None
                        and watch.trades_today == trades_before
                    )
                    if rejected:
                        failed = EngineError(
                            "the broker rejected the order: "
                            + (watch.last_error or "no reason given")
                        )
            self._persist()

        if failed is not None:
            if created:
                try:
                    await self.remove_watch(watch.id)
                except EngineError:
                    pass
            raise failed
        log.warning(
            "engine: MANUAL %s from the charts page: %s (%s)",
            instrument.symbol, ticket.describe(), self.cfg.mode,
        )
        return {
            "watch": watch.as_dict(),
            "ticket": ticket.as_dict(),
            "reference_price": round(reference, 2),
            "stop_price": stop,
            "target_price": target,
            "mode": self.cfg.mode,
        }

    async def _check_gtt(self, watch: Watch, ltp: float | None) -> None:
        """Fire a pending GTT once the live price reaches its trigger."""
        ticket = watch.ticket
        if ticket is None or ticket.order_type != "GTT" or not ticket.trigger_price:
            watch.state = WatchState.WATCHING
            watch.ticket = None
            watch.notes = "GTT dropped: its order details were missing"
            return
        if ltp is None:
            watch.notes = self._gtt_note(ticket, None) + "; no live price yet"
            return
        hit = ltp >= ticket.trigger_price if ticket.trigger_above else ltp <= ticket.trigger_price
        if not hit:
            watch.notes = self._gtt_note(ticket, ltp)
            return

        allowed, why = self._entries_allowed(ticket.product)
        if allowed and watch.trades_today >= self.cfg.engine.max_trades_per_day:
            allowed, why = False, (
                f"max_trades_per_day ({self.cfg.engine.max_trades_per_day}) reached"
            )
        if not allowed:
            watch.notes = (
                f"GTT trigger {ticket.trigger_price:.2f} reached (LTP {ltp:.2f}) but entries "
                f"are blocked: {why}; still waiting"
            )
            return

        reference = float(ticket.limit_price or ltp)
        stop, target = self._ticket_levels(watch.instrument, watch.stop_loss_pct, ticket, reference)
        try:
            if ticket.exit_mode != "strategy":
                self._check_ticket_levels(ticket, reference, stop, target)
        except EngineError as exc:
            # The price went straight through the order's own stop or target before the
            # trigger was seen; entering now would break the plan it was placed with.
            watch.ticket = None
            watch.state = WatchState.WATCHING
            watch.last_error = f"GTT cancelled at its trigger: {exc}"
            log.warning("engine: %s (%s)", watch.last_error, watch.instrument.symbol)
            return

        watch.direction = ticket.direction
        approval = self._manual_approval(
            watch,
            quantity=ticket.quantity,
            reference=reference,
            stop_price=stop,
            target_price=target,
            snapshot=Snapshot(ltp=ltp),
            note=f"GTT triggered at LTP {ltp:.2f}",
            checks={"manual_override": True, "gtt_triggered": True},
            product=ticket.product,
            exit_mode=ticket.exit_mode,
        )
        try:
            await self._place_entry(
                watch,
                approval,
                order_type=OrderType.LIMIT if ticket.limit_price else OrderType.MARKET,
                price=ticket.limit_price or 0.0,
            )
        except BrokerError as exc:
            approval.status = "rejected"
            approval.note = f"{approval.note}: {exc}"
            watch.approval_id = None
            if exc.retryable:
                watch.last_error = f"GTT triggered but the order failed; retrying: {exc}"
                return
            watch.ticket = None
            watch.state = WatchState.WATCHING
            watch.last_error = f"GTT triggered at {ltp:.2f} but the order was refused: {exc}"
            log.error("engine: %s (%s)", watch.last_error, watch.instrument.symbol)
            return
        log.warning(
            "engine: GTT fired for %s at LTP %.2f: %s",
            watch.instrument.symbol, ltp, ticket.describe(),
        )

    async def cancel_entry(self, watch_id: str) -> dict:
        """Cancel a pending GTT, or an entry order still working at the broker."""
        watch = self.watches.get(watch_id)
        if watch is None:
            raise EngineError(f"no such watch: {watch_id}")
        async with self._lock_for(watch.id):
            if watch.state is WatchState.GTT_PENDING:
                watch.ticket = None
                watch.state = WatchState.WATCHING
                watch.notes = "GTT order cancelled"
                watch.last_error = ""
                watch.touch()
                self._persist()
                return watch.as_dict()
            if watch.state is WatchState.ENTRY_PLACED and watch.entry_order is not None:
                ok = await self._cancel_resting_entry(watch, "cancelled from the console")
                watch.touch()
                self._persist()
                if not ok:
                    if watch.position is not None:
                        raise EngineError(
                            "the order filled before it could be cancelled; it is now an "
                            "open position"
                        )
                    raise EngineError(watch.last_error or "the broker refused the cancel")
                return watch.as_dict()
        raise EngineError("nothing to cancel: no GTT is pending and no entry order is working")

    def entry_block_reason(self, new_positions: int = 1, product: str = "INTRADAY") -> str:
        """Why `new_positions` entries cannot all be opened now, or "" if they can.

        Used before a basket sends anything, so the position cap cannot stop it after
        the first few legs are already on.
        """
        allowed, why = self._entries_allowed(product)
        if not allowed:
            return why
        active = sum(1 for w in self.watches.values() if w.state in ACTIVE_STATES)
        cap = self.cfg.engine.max_open_positions
        if active + new_positions > cap:
            return (
                f"{new_positions} new positions would exceed max_open_positions ({cap}) "
                f"with {active} already open; raise it on the Strategy tab"
            )
        return ""

    # ------------------------------------------------------------ diagnostics
    async def diagnose(self, watch_id: str) -> dict:
        watch = self.watches.get(watch_id)
        if watch is None:
            raise EngineError(f"no such watch: {watch_id}")
        today = self.now().date()
        prices = await self.broker.ltp([watch.instrument])
        ltp = prices.get(watch.instrument.security_id)
        ind = await self._indicators(watch, today)
        entry, entry_side = self._entry_signal(watch, ind, ltp)
        # The same evaluation an open position gets, including live rows.
        outcome, _snapshot = await self._exit_rules_outcome(watch, today, ltp)
        rules = effective_rules(self._strategy(watch))
        return {
            "watch": watch.as_dict(ltp),
            "entry_side": entry_side.value,
            "entry": entry.as_dict(),
            "exit": {
                "would_exit": ExitReason.EXIT_RULE.value if outcome.fired else None,
                "notes": [outcome.text],
                "rules": [r.as_dict() for r in outcome.rows],
                "rules_text": explain(rules),
                "snapshot": ind.snapshot().as_dict(),
            },
            "timeframe_minutes": watch.timeframe_minutes,
            "closed_candles": len(ind.series),
            "warmup_required": self._strategy(watch).warmup_bars(),
            "workspace": ws_mod.of_watch(watch),
        }
