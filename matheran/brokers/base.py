"""Broker-agnostic interface.

Adding a broker means implementing this one class. The engine, strategy and API
never import a broker module directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from ..candles import CandleSeries
from ..models import Instrument, OrderStatus, OrderType, Side


class BrokerError(RuntimeError):
    """Raised for broker-reported failures (auth, validation, rejected order)."""

    def __init__(self, message: str, *, code: str = "", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(slots=True)
class PlacedOrder:
    broker_order_id: str
    status: OrderStatus
    message: str = ""


@dataclass(slots=True)
class OrderState:
    broker_order_id: str
    status: OrderStatus
    filled_quantity: int = 0
    average_price: float = 0.0
    message: str = ""


@dataclass(slots=True)
class BrokerPosition:
    security_id: str
    segment: str
    quantity: int
    average_price: float
    symbol: str = ""


class Broker(ABC):
    name: str = "base"
    supports_live_orders: bool = False

    # ---- lifecycle ----
    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    @abstractmethod
    async def health(self) -> dict:
        """Cheap call that proves credentials work."""

    # ---- instruments ----
    @abstractmethod
    async def resolve_equity(self, symbol: str, exchange: str = "NSE") -> Instrument:
        """Look up a cash-segment instrument by trading symbol."""

    @abstractmethod
    async def option_chain_instruments(
        self, underlying: str, expiry: str | None = None
    ) -> list[Instrument]:
        """Every option contract for an underlying and expiry."""

    @abstractmethod
    async def index_instrument(self, underlying: str) -> Instrument | None:
        """Spot/index instrument used to locate the ATM strike."""

    @abstractmethod
    async def expiries(self, underlying: str) -> list[str]:
        """Sorted YYYY-MM-DD expiries available for the underlying."""

    # ---- market data ----
    @abstractmethod
    async def intraday_candles(
        self, instrument: Instrument, day: date, interval_minutes: int = 1
    ) -> CandleSeries:
        """1-minute (or interval) candles for the given day."""

    async def history_candles(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        """Candles for the completed sessions from `start` to `end`, both inclusive.

        `interval_minutes` is 1440 for one candle per session, otherwise a bar length
        in minutes; any finer interval that divides it is fine too, because the caller
        resamples. Intraday bars are anchored at the session open and a session candle
        is stamped with its session open. Optional: without it, long timeframes are
        built from intraday_candles alone (timeframes.load_series).
        """
        raise BrokerError(f"{self.name} does not serve historical candles")

    @abstractmethod
    async def ltp(self, instruments: list[Instrument]) -> dict[str, float]:
        """Batched last traded price keyed by security_id."""

    # ---- trading ----
    @abstractmethod
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
        """`product_type` is INTRADAY (squared off the same day) or DELIVERY (carried:
        CNC for shares, NRML/margin for futures and options); each adapter maps it to
        its own product codes."""

    @abstractmethod
    async def order_state(self, broker_order_id: str) -> OrderState: ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool: ...

    @abstractmethod
    async def positions(self) -> list[BrokerPosition]: ...

    async def holdings(self) -> list[BrokerPosition]:
        """Delivery shares held in the demat account (bought on an earlier day).

        A delivery position moves out of positions() and into holdings once it
        settles, so a restart checks both before deciding a delivery trade is gone.
        """
        return []
