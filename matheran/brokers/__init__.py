"""Broker registry.

Two axes: who executes orders (`broker.name`) and who supplies market data
(`broker.data_broker`). They can be different brokers - the reason this exists is
that Dhan gives Trading APIs away free but charges for Data APIs, while Upstox serves
candles free and without any credentials.
"""

from __future__ import annotations

import logging

from ..config import Config
from .base import Broker, BrokerError, BrokerPosition, OrderState, PlacedOrder
from .composite import CompositeBroker
from .dhan import DhanBroker
from .paper import PaperBroker
from .stoxkart import StoxkartBroker
from .upstox import UpstoxData

log = logging.getLogger(__name__)

__all__ = [
    "Broker",
    "BrokerError",
    "BrokerPosition",
    "OrderState",
    "PlacedOrder",
    "CompositeBroker",
    "DhanBroker",
    "PaperBroker",
    "StoxkartBroker",
    "UpstoxData",
    "build_broker",
]


def _build_execution(name: str, cfg: Config) -> Broker:
    s = cfg.secrets
    if name == "dhan":
        return DhanBroker(
            client_id=s.dhan_client_id or "",
            access_token=s.dhan_access_token or "",
            cache_dir=cfg.cache_dir,
        )
    if name == "stoxkart":
        return StoxkartBroker(
            api_key=s.stoxkart_api_key or "",
            api_secret=s.stoxkart_api_secret or "",
            client_id=s.stoxkart_client_id or "",
            password=s.stoxkart_password or "",
            data_broker=None,
        )
    if name == "paper":
        return PaperBroker()
    raise BrokerError(f"unknown broker '{name}'")


def _build_data(name: str, cfg: Config) -> Broker | None:
    """Market-data provider, or None to let the execution broker supply data."""
    if not name or name == "synthetic":
        return None
    if name == "upstox":
        return UpstoxData(
            cache_dir=cfg.cache_dir,
            access_token=cfg.secrets.upstox_access_token,
        )
    if name == "dhan":
        return DhanBroker(
            client_id=cfg.secrets.dhan_client_id or "",
            access_token=cfg.secrets.dhan_access_token or "",
            cache_dir=cfg.cache_dir,
        )
    raise BrokerError(f"unknown data broker '{name}'")


def build_broker(cfg: Config) -> Broker:
    """Assemble the broker for the configured mode, execution broker and data source.

    In paper mode every order is simulated locally and nothing reaches an exchange,
    but market data is still real whenever a provider is available.
    """
    name = cfg.broker.name.lower()
    data_name = (cfg.broker.data_broker or "").lower()

    # ---- market data ----
    data: Broker | None = None
    if data_name:
        try:
            data = _build_data(data_name, cfg)
        except BrokerError as exc:
            log.warning("data provider '%s' unavailable (%s)", data_name, exc)

    # ---- live: real orders ----
    if cfg.live:
        execution = _build_execution(name, cfg)
        if not execution.supports_live_orders:
            raise BrokerError(
                f"broker '{name}' cannot place live orders in this build; "
                "set mode: paper in config.yaml"
            )
        log.warning("LIVE MODE: orders will be sent to %s", name)
        if data is not None:
            return CompositeBroker(execution=execution, data=data)
        return execution

    # ---- paper: simulated fills ----
    if name == "paper" and data is None:
        if cfg.secrets.dhan_access_token and cfg.secrets.dhan_client_id:
            return PaperBroker(data_broker=_build_execution("dhan", cfg))
        log.warning("paper mode with synthetic market data (no data provider configured)")
        return PaperBroker()

    if data is not None:
        # Real data, simulated fills. The data provider also answers instrument
        # lookups when the execution broker has no credentials.
        if name == "paper":
            return PaperBroker(data_broker=data)
        try:
            execution = _build_execution(name, cfg)
        except BrokerError as exc:
            log.warning("paper mode: %s unavailable (%s), using the data provider alone", name, exc)
            return PaperBroker(data_broker=data)
        return PaperBroker(data_broker=CompositeBroker(execution=execution, data=data))

    try:
        return PaperBroker(data_broker=_build_execution(name, cfg))
    except BrokerError as exc:
        log.warning("paper mode: %s falling back to synthetic data (%s)", name, exc)
        return PaperBroker()
