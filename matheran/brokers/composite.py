"""Split market data and order execution across two brokers.

The motivating case: Dhan charges ₹499/month for Data APIs but nothing for Trading
APIs, while Upstox serves candles free and without authentication. Pairing them gives
free data with Dhan execution.

Instrument resolution deliberately goes to the *execution* broker, because the
resulting Instrument carries the security_id that orders are placed against. The data
provider translates that into its own identifier (see UpstoxData.data_key_for). If the
execution broker cannot resolve instruments - no credentials, or a data-only build -
the data provider is used as a fallback and a warning is logged, because in that state
orders would be rejected.
"""

from __future__ import annotations

import logging
from datetime import date

from ..candles import CandleSeries
from ..models import Instrument, OrderType, Side
from .base import Broker, BrokerError, BrokerPosition, OrderState, PlacedOrder

log = logging.getLogger(__name__)


class CompositeBroker(Broker):
    def __init__(self, *, execution: Broker, data: Broker):
        self.execution = execution
        self.data = data
        self.name = f"{execution.name}+{data.name}"
        self.supports_live_orders = execution.supports_live_orders

    @property
    def data_source(self) -> str:
        return getattr(self.data, "data_source", self.data.name)

    async def startup(self) -> None:
        await self.execution.startup()
        await self.data.startup()

    async def shutdown(self) -> None:
        for broker in (self.execution, self.data):
            try:
                await broker.shutdown()
            except Exception as exc:  # noqa: BLE001
                log.warning("composite: %s shutdown complained: %s", broker.name, exc)

    async def health(self) -> dict:
        out: dict = {"broker": self.name, "execution": self.execution.name,
                     "data_source": self.data_source}
        try:
            out["execution_health"] = await self.execution.health()
        except BrokerError as exc:
            out["execution_error"] = str(exc)
        try:
            out["data_health"] = await self.data.health()
        except BrokerError as exc:
            out["data_error"] = str(exc)
        return out

    # ------------------------------------------------------------ instruments
    async def _resolve(self, method: str, *args, **kwargs):
        try:
            return await getattr(self.execution, method)(*args, **kwargs)
        except BrokerError as exc:
            log.warning(
                "composite: %s.%s failed (%s); falling back to %s. Orders would be "
                "rejected in this state.",
                self.execution.name, method, exc, self.data.name,
            )
            return await getattr(self.data, method)(*args, **kwargs)

    async def resolve_equity(self, symbol: str, exchange: str = "NSE") -> Instrument:
        return await self._resolve("resolve_equity", symbol, exchange)

    async def option_chain_instruments(
        self, underlying: str, expiry: str | None = None
    ) -> list[Instrument]:
        return await self._resolve("option_chain_instruments", underlying, expiry)

    async def index_instrument(self, underlying: str) -> Instrument | None:
        # The spot price is only ever used to locate the ATM strike, so the data
        # provider is the better source: it is the one that can actually quote it.
        found = await self.data.index_instrument(underlying)
        if found is not None:
            return found
        return await self.execution.index_instrument(underlying)

    async def expiries(self, underlying: str) -> list[str]:
        return await self._resolve("expiries", underlying)

    async def instrument_by_security_id(self, segment: str, security_id: str):
        getter = getattr(self.execution, "instrument_by_security_id", None)
        if getter is not None:
            found = await getter(segment, security_id)
            if found is not None:
                return found
        getter = getattr(self.data, "instrument_by_security_id", None)
        if getter is not None:
            return await getter(segment, security_id)
        return None

    # ----------------------------------------------------------- market data
    async def intraday_candles(
        self, instrument: Instrument, day: date, interval_minutes: int = 1
    ) -> CandleSeries:
        return await self.data.intraday_candles(instrument, day, interval_minutes)

    async def history_candles(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        return await self.data.history_candles(instrument, interval_minutes, start, end)

    async def ltp(self, instruments: list[Instrument]) -> dict[str, float]:
        return await self.data.ltp(instruments)

    # --------------------------------------------------------------- trading
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
        return await self.execution.place_order(
            instrument=instrument,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            correlation_id=correlation_id,
            product_type=product_type,
        )

    async def order_state(self, broker_order_id: str) -> OrderState:
        return await self.execution.order_state(broker_order_id)

    async def cancel_order(self, broker_order_id: str) -> bool:
        return await self.execution.cancel_order(broker_order_id)

    async def positions(self) -> list[BrokerPosition]:
        return await self.execution.positions()

    async def holdings(self) -> list[BrokerPosition]:
        return await self.execution.holdings()
