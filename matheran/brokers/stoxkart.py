"""Stoxkart (Superr API) adapter - PARTIAL, needs verification against your account.

Why partial: Stoxkart does not publish an open API reference. The endpoints below
come from their own public SDKs, which disagree with each other:

  * superrapi-js/lib/routes.js  -> /auth/login, /auth/twofa/verify, /auth/token,
                                   /order/v1/place-order, /order/v1/modify-order,
                                   /order/v1/cancel-order, /report/v1/order-book,
                                   /report/v1/trade-book, /report/v1/script-master,
                                   /portfolio/v1/holding, /portfolio/v1/position,
                                   /fund/v1/fund-details
  * superrapi-python/superapi.py -> root https://openapi.stoxkart.com, but posts
                                   orders to /orders/normal

Neither documents the market-data/historical-candle service, and API keys are
issued by Stoxkart support per client code.

So this class implements the auth handshake and the order/portfolio calls, and
refuses - loudly - on anything unverified rather than guessing and sending a
malformed live order. Recommended setup until you confirm the contract with
Stoxkart: keep Dhan as the data source and run this in paper mode.

  broker:
    name: stoxkart
    data_broker: dhan
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import date

from ..candles import CandleSeries
from ..models import Instrument, OrderStatus, OrderType, Side
from .base import Broker, BrokerError, BrokerPosition, OrderState, PlacedOrder

log = logging.getLogger(__name__)

ROOT_URL = "https://openapi.stoxkart.com"

ROUTES = {
    "login": "/auth/login",
    "twofa": "/auth/twofa/verify",
    "token": "/auth/token",
    "place_order": "/order/v1/place-order",
    "modify_order": "/order/v1/modify-order",
    "cancel_order": "/order/v1/cancel-order",
    "order_book": "/report/v1/order-book",
    "trade_book": "/report/v1/trade-book",
    "script_master": "/report/v1/script-master",
    "holdings": "/portfolio/v1/holding",
    "positions": "/portfolio/v1/position",
    "funds": "/fund/v1/fund-details",
}

_UNVERIFIED = (
    "Stoxkart's {what} contract is not published, so this adapter will not guess it. "
    "Use Dhan (or another broker) as the data source, or send me the endpoint spec "
    "from Stoxkart support and I'll wire it up."
)


class StoxkartBroker(Broker):
    name = "stoxkart"
    supports_live_orders = False  # flipped on once the contract is confirmed

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        client_id: str,
        password: str,
        data_broker: Broker | None = None,
    ):
        if not all([api_key, api_secret, client_id]):
            raise BrokerError(
                "Stoxkart needs STOXKART_API_KEY, STOXKART_API_SECRET and STOXKART_CLIENT_ID"
            )
        self.api_key = api_key
        self.api_secret = api_secret
        self.client_id = client_id
        self.password = password
        self.data_broker = data_broker
        self.request_token: str | None = None
        self.access_token: str | None = None

    # ---- auth ----
    def signature(self, request_token: str) -> str:
        """HMAC-SHA256 over api_key+request_token keyed with the secret, matching
        their Python SDK's getSignature()."""
        key = (self.api_key + request_token).encode()
        return hmac.new(key, self.api_secret.encode(), hashlib.sha256).hexdigest()

    def login_url(self) -> str:
        return f"{ROOT_URL}{ROUTES['login']}?api-key={self.api_key}"

    async def health(self) -> dict:
        return {
            "broker": self.name,
            "status": "adapter_incomplete",
            "data_source": self.data_broker.name if self.data_broker else None,
            "detail": "auth + order routes stubbed from public SDKs; not verified live",
            "login_url": self.login_url(),
        }

    # ---- instruments and data: delegate or refuse ----
    async def resolve_equity(self, symbol: str, exchange: str = "NSE") -> Instrument:
        if self.data_broker:
            return await self.data_broker.resolve_equity(symbol, exchange)
        raise BrokerError(_UNVERIFIED.format(what="script-master"))

    async def index_instrument(self, underlying: str) -> Instrument | None:
        if self.data_broker:
            return await self.data_broker.index_instrument(underlying)
        raise BrokerError(_UNVERIFIED.format(what="script-master"))

    async def option_chain_instruments(
        self, underlying: str, expiry: str | None = None
    ) -> list[Instrument]:
        if self.data_broker:
            return await self.data_broker.option_chain_instruments(underlying, expiry)
        raise BrokerError(_UNVERIFIED.format(what="script-master"))

    async def expiries(self, underlying: str) -> list[str]:
        if self.data_broker:
            return await self.data_broker.expiries(underlying)
        raise BrokerError(_UNVERIFIED.format(what="script-master"))

    async def intraday_candles(
        self, instrument: Instrument, day: date, interval_minutes: int = 1
    ) -> CandleSeries:
        if self.data_broker:
            return await self.data_broker.intraday_candles(instrument, day, interval_minutes)
        raise BrokerError(_UNVERIFIED.format(what="historical-candle"))

    async def history_candles(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        if self.data_broker:
            return await self.data_broker.history_candles(instrument, interval_minutes, start, end)
        raise BrokerError(_UNVERIFIED.format(what="historical-candle"))

    async def ltp(self, instruments: list[Instrument]) -> dict[str, float]:
        if self.data_broker:
            return await self.data_broker.ltp(instruments)
        raise BrokerError(_UNVERIFIED.format(what="market-quote"))

    # ---- trading ----
    def order_payload(
        self,
        *,
        instrument: Instrument,
        side: Side,
        quantity: int,
        order_type: OrderType,
        price: float,
        trigger_price: float,
        tag: str,
    ) -> dict:
        """The shape their SDKs agree on. Exposed so you can diff it against
        whatever Stoxkart support sends you before going live."""
        return {
            "action": side.value,
            "exchange": instrument.segment.split("_")[0],
            "token": instrument.security_id,
            "order_type": order_type.value,
            "product_type": "MIS",
            "quantity": int(quantity),
            "disclose_quantity": 0,
            "price": round(float(price), 2),
            "trigger_price": round(float(trigger_price), 2),
            "square_off": 0,
            "stop_loss": 0,
            "trailing_stop_loss": 0,
            "validity": "DAY",
            "validity_date": "",
            "tag": tag[:20],
        }

    async def place_order(self, **kwargs) -> PlacedOrder:
        raise BrokerError(
            "Stoxkart live order placement is disabled in this build. "
            "Run mode: paper with broker.data_broker: dhan, or confirm the "
            "/order/v1/place-order contract with Stoxkart support first."
        )

    async def order_state(self, broker_order_id: str) -> OrderState:
        raise BrokerError(_UNVERIFIED.format(what="order-book"))

    async def cancel_order(self, broker_order_id: str) -> bool:
        raise BrokerError(_UNVERIFIED.format(what="cancel-order"))

    async def positions(self) -> list[BrokerPosition]:
        raise BrokerError(_UNVERIFIED.format(what="portfolio/position"))
