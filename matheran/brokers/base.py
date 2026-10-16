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
from ..timeutil import now_ist


class BrokerError(RuntimeError):
    """Raised for broker-reported failures (auth, validation, rejected order)."""

    def __init__(
        self, message: str, *, code: str = "", retryable: bool = False, status: int = 0
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status = status  # the HTTP status when known, else 0


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

    async def today_candles(
        self, instrument: Instrument, interval_minutes: int = 1, *, day: date | None = None
    ) -> CandleSeries:
        """Today's candles, the forming one included, at interval_minutes or any finer
        interval that divides it (DAY means one session candle). One request where the
        provider allows. This default asks for 1-minute candles, which every broker
        already serves for the engine (Dhan, for one, has no 3- or 9-minute interval),
        and trims them to `day` (default: today in IST; the scanner passes its pinned
        scan day); the caller resamples."""
        today = day or now_ist().date()
        series = await self.intraday_candles(instrument, today, 1)
        return CandleSeries([c for c in series.candles if c.ts.date() == today])

    async def history_window(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        """history_candles for one window, in as few requests as the provider allows.
        Same contract (completed sessions only, start..end inclusive, finer intervals
        allowed)."""
        return await self.history_candles(instrument, interval_minutes, start, end)

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
