"""Paper broker: real market data, simulated fills.

Two shapes:
  * wrapping a live data broker (Dhan) - real candles and LTP, no orders sent
  * standalone with a synthetic random walk - lets you exercise the whole API
    with no broker credentials at all. Always labelled `synthetic` in responses.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..candles import Candle, CandleSeries
from ..models import Instrument, OrderStatus, OrderType, Side, new_id
from ..timeutil import IST, now_ist, previous_trading_day, session_close, session_open
from .base import Broker, BrokerError, BrokerPosition, OrderState, PlacedOrder

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _SimOrder:
    broker_order_id: str
    instrument: Instrument
    side: Side
    order_type: OrderType
    quantity: int
    price: float
    trigger_price: float
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    average_price: float = 0.0
    created_at: datetime = field(default_factory=now_ist)
    message: str = ""


class SyntheticFeed:
    """Deterministic-per-instrument random walk on a 1-minute grid."""

    BASE_PRICES = {"NIFTY": 25000.0, "BANKNIFTY": 72000.0, "FINNIFTY": 24000.0}

    def __init__(self) -> None:
        self._cache: dict[str, CandleSeries] = {}

    def _seed(self, instrument: Instrument) -> int:
        digest = hashlib.sha256(instrument.security_id.encode()).hexdigest()[:8]
        return int(digest, 16)

    def _base_price(self, instrument: Instrument) -> float:
        if instrument.is_option:
            return 120.0 + (self._seed(instrument) % 80)
        name = (instrument.underlying or instrument.symbol).upper()
        if name in self.BASE_PRICES:
            return self.BASE_PRICES[name]
        return 500.0 + (self._seed(instrument) % 2000)

    def candles(self, instrument: Instrument, day: date) -> CandleSeries:
        key = f"{instrument.security_id}:{day.isoformat()}"
        if key in self._cache:
            return self._cache[key]

        rng = random.Random(self._seed(instrument) ^ day.toordinal())
        price = self._base_price(instrument)
        vol_scale = price * 0.0012

        candles: list[Candle] = []
        for offset in range(5, 0, -1):
            d = previous_trading_day(day, offset)
            candles.extend(self._session(rng, d, instrument, price, vol_scale))
            if candles:
                price = candles[-1].close
        candles.extend(self._session(rng, day, instrument, price, vol_scale, cap_to_now=True))

        series = CandleSeries(candles)
        self._cache[key] = series
        return series

    def history(
        self, instrument: Instrument, interval: int, start: date, end: date
    ) -> CandleSeries:
        """Earlier sessions for the long timeframes: one candle per session, or bars of
        `interval` minutes. The path walks back from the base price, so it meets the
        recent 1-minute sessions roughly where they begin."""
        days = []
        d = end
        while d >= start:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        if not days:
            return CandleSeries([])
        seed = self._seed(instrument)
        price = self._base_price(instrument)
        path: dict[date, tuple[float, float]] = {}
        for d in days:  # newest first
            rng = random.Random(seed ^ d.toordinal())
            close = max(price, 0.05)
            open_ = max(close / (1 + rng.gauss(0.0004, 0.011)), 0.05)
            path[d] = (open_, close)
            price = open_ * (1 + rng.gauss(0, 0.003))
        out: list[Candle] = []
        for d in reversed(days):
            open_, close = path[d]
            rng = random.Random(seed ^ d.toordinal() ^ (interval * 7919))
            if interval >= 1440:
                wick = abs(rng.gauss(0, 0.004))
                out.append(Candle(
                    ts=session_open(instrument.segment, d),
                    open=round(open_, 2), close=round(close, 2),
                    high=round(max(open_, close) * (1 + wick), 2),
                    low=round(max(min(open_, close) * (1 - wick), 0.05), 2),
                    volume=float(rng.randint(200_000, 4_000_000)),
                ))
            else:
                out.extend(self._bars_between(rng, instrument, d, open_, close, interval))
        return CandleSeries(out)

    def _bars_between(
        self, rng: random.Random, instrument: Instrument, day: date,
        open_: float, close: float, interval: int,
    ) -> list[Candle]:
        start = session_open(instrument.segment, day)
        length = (session_close(instrument.segment, day) - start).total_seconds() / 60
        n = max(1, math.ceil(length / interval))
        noise = open_ * 0.0012 * math.sqrt(interval)
        price = open_
        out: list[Candle] = []
        for k in range(n):
            step = (close - price) / (n - k)
            moves = [price + step * (j + 1) / 4 + rng.gauss(0, noise / 2) for j in range(4)]
            o = price
            c = close if k == n - 1 else moves[-1]
            out.append(Candle(
                ts=start + timedelta(minutes=k * interval),
                open=round(o, 2),
                high=round(max(o, c, *moves), 2),
                low=round(max(min(o, c, *moves), 0.05), 2),
                close=round(max(c, 0.05), 2),
                volume=float(rng.randint(500, 20000) * interval),
            ))
            price = max(c, 0.05)
        return out

    def _session(
        self,
        rng: random.Random,
        day: date,
        instrument: Instrument,
        start_price: float,
        vol_scale: float,
        cap_to_now: bool = False,
    ) -> list[Candle]:
        start = session_open(instrument.segment, day)
        end = session_close(instrument.segment, day)
        if cap_to_now:
            end = min(end, now_ist())
        out: list[Candle] = []
        price = start_price
        ts = start
        drift = rng.uniform(-0.00004, 0.00006)
        while ts < end:
            o = price
            steps = [price * (1 + drift) + rng.gauss(0, vol_scale) for _ in range(4)]
            h = max([o, *steps])
            l = min([o, *steps])
            c = steps[-1]
            price = max(c, 0.05)
            out.append(
                Candle(
                    ts=ts,
                    open=round(o, 2),
                    high=round(h, 2),
                    low=round(max(l, 0.05), 2),
                    close=round(price, 2),
                    volume=float(rng.randint(500, 20000)),
                )
            )
            ts += timedelta(minutes=1)
        return out


class PaperBroker(Broker):
    name = "paper"
    supports_live_orders = False

    def __init__(self, data_broker: Broker | None = None):
        self.data_broker = data_broker
        self.synthetic = SyntheticFeed() if data_broker is None else None
        self._orders: dict[str, _SimOrder] = {}
        self._positions: dict[str, BrokerPosition] = {}

    @property
    def data_source(self) -> str:
        if self.data_broker is None:
            return "synthetic"
        # Unwrap composites so this names who actually serves the candles, not the
        # execution+data pair.
        return getattr(self.data_broker, "data_source", self.data_broker.name)

    async def startup(self) -> None:
        if self.data_broker:
            await self.data_broker.startup()

    async def shutdown(self) -> None:
        if self.data_broker:
            await self.data_broker.shutdown()

    async def health(self) -> dict:
        info = {"broker": "paper", "data_source": self.data_source, "orders_simulated": True}
        if self.data_broker:
            try:
                info["upstream"] = await self.data_broker.health()
            except BrokerError as exc:
                info["upstream_error"] = str(exc)
        return info

    # ---- instruments ----
    async def resolve_equity(self, symbol: str, exchange: str = "NSE") -> Instrument:
        if self.data_broker:
            return await self.data_broker.resolve_equity(symbol, exchange)
        segment = "NSE_EQ" if exchange.upper() == "NSE" else "BSE_EQ"
        return Instrument(
            security_id=f"SYN{abs(hash(symbol.upper())) % 100000}",
            symbol=symbol.upper(),
            segment=segment,
            instrument_type="EQUITY",
            display_name=f"{symbol.upper()} (synthetic)",
            lot_size=1,
            tick_size=0.05,
        )

    async def index_instrument(self, underlying: str) -> Instrument | None:
        if self.data_broker:
            return await self.data_broker.index_instrument(underlying)
        return Instrument(
            security_id=f"SYNIDX{abs(hash(underlying.upper())) % 1000}",
            symbol=underlying.upper(),
            segment="IDX_I",
            instrument_type="INDEX",
            display_name=f"{underlying.upper()} (synthetic)",
        )

    async def expiries(self, underlying: str) -> list[str]:
        if self.data_broker:
            return await self.data_broker.expiries(underlying)
        today = now_ist().date()
        days_to_tuesday = (1 - today.weekday()) % 7 or 7
        return [(today + timedelta(days=days_to_tuesday + 7 * i)).isoformat() for i in range(3)]

    async def option_chain_instruments(
        self, underlying: str, expiry: str | None = None
    ) -> list[Instrument]:
        if self.data_broker:
            return await self.data_broker.option_chain_instruments(underlying, expiry)

        name = underlying.upper()
        step = 100.0 if name == "BANKNIFTY" else 50.0
        expiries = await self.expiries(name)
        target = expiry or expiries[0]
        # Centre the synthetic strikes on the synthetic spot, otherwise the random
        # walk drifts out of the strike range and one side of the chain goes missing.
        index = await self.index_instrument(name)
        spot = SyntheticFeed.BASE_PRICES.get(name, 25000.0)
        if index is not None:
            prices = await self.ltp([index])
            spot = prices.get(index.security_id, spot)
        atm = round(spot / step) * step
        out: list[Instrument] = []
        for k in range(-25, 26):
            strike = atm + k * step
            for opt in ("CE", "PE"):
                out.append(
                    Instrument(
                        security_id=f"SYN{name}{int(strike)}{opt}",
                        symbol=f"{name}-{target}-{int(strike)}-{opt}",
                        segment="NSE_FNO",
                        instrument_type="OPTIDX",
                        display_name=f"{name} {int(strike)} {opt} (synthetic)",
                        lot_size=75 if name == "NIFTY" else 30,
                        tick_size=0.05,
                        expiry=target,
                        strike=strike,
                        option_type=opt,
                        underlying=name,
                    )
                )
        return out

    # ---- market data ----
    async def intraday_candles(
        self, instrument: Instrument, day: date, interval_minutes: int = 1
    ) -> CandleSeries:
        if self.data_broker:
            return await self.data_broker.intraday_candles(instrument, day, interval_minutes)
        return self.synthetic.candles(instrument, day)

    async def history_candles(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        if self.data_broker:
            return await self.data_broker.history_candles(instrument, interval_minutes, start, end)
        return self.synthetic.history(instrument, interval_minutes, start, end)

    async def ltp(self, instruments: list[Instrument]) -> dict[str, float]:
        if self.data_broker:
            prices = await self.data_broker.ltp(instruments)
        else:
            prices = {}
            today = now_ist().date()
            for inst in instruments:
                series = self.synthetic.candles(inst, today)
                if series:
                    prices[inst.security_id] = series.candles[-1].close
        await self._settle_resting_orders(prices)
        return prices

    # ---- simulated trading ----
    async def place_order(
        self,
        *,
        instrument: Instrument,
        side: Side,
        quantity: int,
        order_type: OrderType,
        price: float = 0.0,
        trigger_price: float = 0.0,
        correlation_id: str = "",
        product_type: str = "INTRADAY",
    ) -> PlacedOrder:
        order_id = new_id("paper")
        order = _SimOrder(
            broker_order_id=order_id,
            instrument=instrument,
            side=side,
            order_type=order_type,
            quantity=int(quantity),
            price=float(price),
            trigger_price=float(trigger_price),
        )
        self._orders[order_id] = order

        if order_type in {OrderType.MARKET, OrderType.LIMIT}:
            prices = await self.ltp([instrument])
            ltp = prices.get(instrument.security_id)
            if order_type is OrderType.LIMIT and price <= 0:
                order.status = OrderStatus.REJECTED
                order.message = "a limit order needs a price"
            elif ltp is None:
                order.status = OrderStatus.REJECTED
                order.message = "no price available to simulate a fill"
            elif order_type is OrderType.MARKET or self._limit_reached(order, ltp):
                # A marketable limit fills at the market, which is never worse than
                # the limit.
                self._fill(order, ltp)
            else:
                # Otherwise it rests until the price comes to it, as at the exchange.
                order.status = OrderStatus.OPEN
                order.message = "resting limit order"
        else:
            order.status = OrderStatus.OPEN
            order.message = "resting stop order"

        return PlacedOrder(
            broker_order_id=order_id, status=order.status, message=order.message
        )

    def _fill(self, order: _SimOrder, fill_price: float) -> None:
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.average_price = round(fill_price, 2)
        key = f"{order.instrument.segment}:{order.instrument.security_id}"
        signed = order.quantity if order.side is Side.BUY else -order.quantity
        pos = self._positions.get(key)
        if pos is None:
            self._positions[key] = BrokerPosition(
                security_id=order.instrument.security_id,
                segment=order.instrument.segment,
                quantity=signed,
                average_price=order.average_price,
                symbol=order.instrument.symbol,
            )
        else:
            new_qty = pos.quantity + signed
            if new_qty == 0:
                del self._positions[key]
            else:
                if (pos.quantity > 0) == (signed > 0):
                    total = abs(pos.quantity) + abs(signed)
                    pos.average_price = (
                        pos.average_price * abs(pos.quantity)
                        + order.average_price * abs(signed)
                    ) / total
                pos.quantity = new_qty

    @staticmethod
    def _limit_reached(order: _SimOrder, ltp: float) -> bool:
        return ltp <= order.price if order.side is Side.BUY else ltp >= order.price

    async def _settle_resting_orders(self, prices: dict[str, float]) -> None:
        for order in self._orders.values():
            if order.status is not OrderStatus.OPEN:
                continue
            ltp = prices.get(order.instrument.security_id)
            if ltp is None:
                continue
            if order.order_type is OrderType.LIMIT:
                if self._limit_reached(order, ltp):
                    # A resting order is filled at its own price, not the print that
                    # reached it: the conservative reading of a coarse price sample.
                    self._fill(order, order.price)
                    order.message = "limit reached (simulated)"
                continue
            if order.order_type in {OrderType.STOP_LOSS, OrderType.STOP_LOSS_MARKET}:
                triggered = (
                    ltp <= order.trigger_price
                    if order.side is Side.SELL
                    else ltp >= order.trigger_price
                )
                if triggered:
                    fill = ltp if order.order_type is OrderType.STOP_LOSS_MARKET else order.price
                    self._fill(order, fill or ltp)
                    order.message = "stop triggered (simulated)"

    async def order_state(self, broker_order_id: str) -> OrderState:
        order = self._orders.get(broker_order_id)
        if order is None:
            raise BrokerError(f"unknown simulated order {broker_order_id}")
        if order.status is OrderStatus.OPEN:
            await self.ltp([order.instrument])
        return OrderState(
            broker_order_id=order.broker_order_id,
            status=order.status,
            filled_quantity=order.filled_quantity,
            average_price=order.average_price,
            message=order.message,
        )

    async def cancel_order(self, broker_order_id: str) -> bool:
        order = self._orders.get(broker_order_id)
        if order is None or order.status in {OrderStatus.FILLED, OrderStatus.REJECTED}:
            return False
        order.status = OrderStatus.CANCELLED
        return True

    async def positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def restore_position(self, instrument: Instrument, quantity: int, average_price: float) -> None:
        """Re-seed a simulated position after a restart.

        Simulated fills live in memory, so without this every paper position - a
        delivery trade carried overnight included - would look closed when the service
        comes back, and the engine would drop it. `quantity` is signed: negative is short.
        """
        if not quantity:
            return
        key = f"{instrument.segment}:{instrument.security_id}"
        self._positions[key] = BrokerPosition(
            security_id=instrument.security_id,
            segment=instrument.segment,
            quantity=int(quantity),
            average_price=float(average_price),
            symbol=instrument.symbol,
        )
