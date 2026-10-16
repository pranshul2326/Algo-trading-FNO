"""HTTP surface: settings, watches, the options scan table, approvals, trades, controls."""

from __future__ import annotations

import asyncio
import logging
import secrets as secrets_mod
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from datetime import datetime

from . import chart_indicators, chart_types, data_source, timeframes
from .baskets import BasketLeg, BasketStore, unit_weights
from .brokers import build_broker
from .brokers.base import BrokerError
from .candles import bar_end
from .chain_page import CHAIN_HTML
from .charts_page import CHARTS_HTML
from .combo import ComboLeg
from .combo import build as build_combo
from .combo_page import COMBO_HTML
from .config import Config, load_config
from .dashboard import DASHBOARD_HTML
from .engine import ACTIVE_STATES, Engine, EngineError
from .models import (
    EXIT_MODES,
    PRODUCTS,
    SL_UNITS,
    TARGET_UNITS,
    TICKET_ORDER_TYPES,
    TRAIL_UNITS,
    Direction,
    TradeTicket,
    WatchState,
)
from .timeutil import IST, now_ist, session_close, session_open
from .rules import catalog as rules_catalog
from .rules import effective_rules, explain, legacy_rules, normalize_rules
from .options import (
    BUILDUP_MINUTES,
    MAX_CHAIN_STRIKES_EACH_SIDE,
    active_expiries,
    oi_chain,
    scan_chain,
    select_chain,
    select_full_chain,
)
from .settings import CREDENTIAL_KEYS, SettingsManager, generate_api_key
from .store import Store

log = logging.getLogger(__name__)

# "testclient" is what Starlette's TestClient reports as the peer host.
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


# --------------------------------------------------------------- request models
_PRODUCT_ALIASES = {"MIS": "INTRADAY", "CNC": "DELIVERY", "NRML": "DELIVERY", "MARGIN": "DELIVERY",
                    "CARRY": "DELIVERY"}
_EXIT_ALIASES = {"sl": "sl_target", "sl_tp": "sl_target", "target": "sl_target",
                 "price": "sl_target", "rules": "strategy", "conditions": "strategy"}


def _product(v: str | None) -> str | None:
    """INTRADAY or DELIVERY; the brokers' own words (MIS, CNC, NRML) are accepted."""
    if v is None or not str(v).strip():
        return None
    text = str(v).strip().upper()
    text = _PRODUCT_ALIASES.get(text, text)
    if text not in PRODUCTS:
        raise ValueError("product must be INTRADAY or DELIVERY")
    return text


def _exit_mode(v: str | None) -> str | None:
    if v is None or not str(v).strip():
        return None
    text = str(v).strip().lower()
    text = _EXIT_ALIASES.get(text, text)
    if text not in EXIT_MODES:
        raise ValueError("exit_mode must be both, sl_target or strategy")
    return text


def _entry_kind(v: str | None) -> str:
    text = (v or "MARKET").strip().upper()
    if text not in ("MARKET", "LIMIT"):
        raise ValueError("order_type must be MARKET or LIMIT")
    return text


class TradeChoices(BaseModel):
    """How an order goes in and comes out. Blank means the watch's or the default."""

    product: str | None = Field(
        None, description="INTRADAY (squared off at the square-off time) or DELIVERY "
        "(carried: CNC for shares, NRML for F&O)",
    )
    exit_mode: str | None = Field(
        None, description="both = SL / target and exit conditions; sl_target = SL / target "
        "only; strategy = exit conditions only (no stop)",
    )

    @field_validator("product")
    @classmethod
    def _p(cls, v: str | None) -> str | None:
        return _product(v)

    @field_validator("exit_mode")
    @classmethod
    def _e(cls, v: str | None) -> str | None:
        return _exit_mode(v)


class CreateWatch(TradeChoices):
    symbol: str = Field(..., description="Trading symbol, e.g. RELIANCE")
    exchange: str = Field("NSE", description="NSE or BSE")
    quantity: int = Field(..., gt=0, description="Number of shares to trade on approval")
    direction: str = Field(
        "LONG",
        description="LONG buys then sells; SHORT sells then buys back, with every entry "
        "and exit condition mirrored and the stop above entry; BOTH takes whichever "
        "side signals, one position at a time.",
    )
    timeframe_minutes: int | None = Field(
        None, description="Minutes: 1, 3, 5, 9, 15, 30, 60, 120, 1440 (day), 10080 (week), "
        "43200 (month)",
    )
    stop_loss_pct: float | None = Field(
        None, gt=0, lt=100, description="Defaults to risk.stop_loss_pct (3%)"
    )
    target_pct: float | None = Field(None, gt=0, description="Optional take-profit")
    notes: str = ""

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("exchange")
    @classmethod
    def _exchange(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in {"NSE", "BSE"}:
            raise ValueError("exchange must be NSE or BSE")
        return v

    @field_validator("direction")
    @classmethod
    def _direction(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in {"LONG", "SHORT", "BOTH"}:
            raise ValueError("direction must be LONG, SHORT or BOTH")
        return v


class CreateOptionWatch(TradeChoices):
    security_id: str | None = Field(
        None, description="Exact contract id from the chain table; skips the lookup below"
    )
    underlying: str | None = Field(None, description="e.g. NIFTY")
    expiry: str | None = Field(None, description="YYYY-MM-DD, or leave empty for nearest")
    strike: float | None = None
    option_type: str | None = Field(None, description="CE or PE")
    lots: int | None = Field(None, gt=0, description="Quantity in lots (preferred)")
    quantity: int | None = Field(None, gt=0, description="Raw quantity; must be a lot multiple")
    timeframe_minutes: int = Field(1, description="options spec uses 1 minute")
    stop_loss_pct: float | None = Field(None, gt=0, lt=100)
    target_pct: float | None = Field(None, gt=0)
    adx_min: float | None = Field(None, description="Defaults to strategy.adx_min (20)")
    notes: str = ""

    @field_validator("option_type")
    @classmethod
    def _opt(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if v not in {"CE", "PE"}:
            raise ValueError("option_type must be CE or PE")
        return v


class RejectBody(BaseModel):
    note: str = ""


class BuyBody(TradeChoices):
    confirm: bool = Field(
        False, description="Required in live mode; this sends a real order"
    )
    note: str = "manual buy"
    direction: str | None = Field(
        None,
        description="LONG (buy) or SHORT (sell). Required for a watch that trades both "
        "ways; must match the watch otherwise.",
    )
    order_type: str = Field(
        "MARKET", description="MARKET, or LIMIT: rests at limit_price until the price comes "
        "to it (cancelled at the no-new-entry cutoff, or the close for delivery)",
    )
    limit_price: float | None = Field(None, gt=0, description="LIMIT price")

    @field_validator("order_type")
    @classmethod
    def _kind(cls, v: str) -> str:
        return _entry_kind(v)

    @field_validator("direction")
    @classmethod
    def _dir(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().upper()
        aliases = {"BUY": "LONG", "SELL": "SHORT"}
        v = aliases.get(v, v)
        if v not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG/BUY or SHORT/SELL")
        return v


class OptionBuyBody(CreateOptionWatch):
    """Create an option watch and buy it immediately."""

    confirm: bool = Field(False, description="Required in live mode")
    order_type: str = Field("MARKET", description="MARKET or LIMIT")
    limit_price: float | None = Field(None, gt=0, description="LIMIT price")

    @field_validator("order_type")
    @classmethod
    def _kind(cls, v: str) -> str:
        return _entry_kind(v)


class BasketLegBody(BaseModel):
    symbol: str = Field(
        ..., description="Chart symbol id, e.g. opt:NIFTY:2026-10-06:22700:CE or eq:NSE:SBIN"
    )
    direction: str = Field("LONG", description="LONG/BUY buys this leg, SHORT/SELL sells it")
    quantity: int | None = Field(None, gt=0, description="Units; must be a lot multiple")
    lots: int | None = Field(
        None, gt=0, description="Lots instead of units (1 lot = 1 share for stocks)"
    )
    label: str = ""

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("symbol is required")
        return v

    @field_validator("direction")
    @classmethod
    def _dir(cls, v: str) -> str:
        v = v.strip().upper()
        v = {"BUY": "LONG", "SELL": "SHORT"}.get(v, v)
        if v not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG/BUY or SHORT/SELL")
        return v


class CreateBasket(TradeChoices):
    name: str = Field("basket", max_length=60)
    legs: list[BasketLegBody] = Field(..., min_length=1, max_length=10)
    timeframe_minutes: int = 5
    stop_loss_pct: float | None = Field(None, gt=0, lt=100)
    target_pct: float | None = Field(None, gt=0)
    notes: str = ""

    @field_validator("timeframe_minutes")
    @classmethod
    def _tf(cls, v: int) -> int:
        if v not in timeframes.MINUTES:
            raise ValueError("timeframe_minutes must be one of "
                             + ", ".join(str(m) for m in timeframes.MINUTES))
        return v


class ExecuteBasketBody(BuyBody):
    """Execute a basket: every leg at market, or every leg as a limit order."""

    limit_prices: dict[str, float] | None = Field(
        None, description="LIMIT only: leg symbol -> limit price, one for every leg"
    )


class HaltBody(BaseModel):
    square_off: bool = Field(False, description="Also exit every open position")
    reason: str = "manual halt"


class CredentialsBody(BaseModel):
    """Credential name -> value.

    Omit a key or send "" to leave it untouched. Send null to clear it.
    """

    values: dict[str, str | None]

    @field_validator("values")
    @classmethod
    def _known(cls, v: dict) -> dict:
        unknown = set(v) - CREDENTIAL_KEYS
        if unknown:
            raise ValueError(f"unknown credential keys: {sorted(unknown)}")
        return v


class ConfigBody(BaseModel):
    mode: str | None = Field(None, description="paper or live")
    broker: dict | None = None
    engine: dict | None = None
    strategy: dict | None = None
    risk: dict | None = None
    options: dict | None = None
    confirm_live: bool = Field(
        False, description="Must be true to switch mode to live, which sends real orders"
    )

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in {"paper", "live"}:
            raise ValueError("mode must be paper or live")
        return v


class ExitRulesBody(BaseModel):
    rules: list | None = Field(
        ..., description="Rows as in strategy.exit_rules; null for the default two"
    )


class ChartTradeBody(TradeChoices):
    """A manual order from a chart pane."""

    symbol: str = Field(
        ..., description="Chart symbol id, e.g. opt:NIFTY:2026-10-06:25000:CE or eq:NSE:SBIN"
    )
    side: str = Field("BUY", description="BUY opens a long, SELL opens a short")
    lots: int | None = Field(None, gt=0, description="Lots (1 lot = 1 share for stocks)")
    quantity: int | None = Field(None, gt=0, description="Units instead of lots")
    order_type: str = Field(
        "MARKET",
        description="MARKET, LIMIT, or GTT - held by the engine until the live price "
        "reaches trigger_price, then sent at market or at limit_price",
    )
    limit_price: float | None = Field(
        None, gt=0, description="LIMIT price, or the limit a triggered GTT uses (blank = market)"
    )
    trigger_price: float | None = Field(None, gt=0, description="GTT trigger price")
    sl_value: float | None = Field(None, gt=0, description="Stop loss; blank = the default %")
    sl_unit: str = Field("pct", description="pct of the entry, or price")
    trail_value: float | None = Field(None, gt=0, description="Trailing stop distance; blank = off")
    trail_unit: str = Field("pct", description="pct of the best price, or pts")
    trail_trigger_pct: float | None = Field(
        None, gt=0, description="Trailing profit: the trail starts once the trade is this % "
        "in profit; blank = trails from the entry",
    )
    target_value: float | None = Field(None, gt=0, description="Target; blank = none")
    target_unit: str = Field("pct", description="pct of the entry, or price")
    use_exit_rules: bool | None = Field(
        None, description="Older clients: false = exit_mode sl_target, true = both"
    )
    timeframe: str = Field("5m", description="Candles the exit conditions read: the chart's")
    confirm: bool = Field(False, description="Required in live mode; this sends a real order")
    note: str = ""

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("symbol is required")
        return v

    @field_validator("side")
    @classmethod
    def _side(cls, v: str) -> str:
        v = {"LONG": "BUY", "SHORT": "SELL"}.get(v.strip().upper(), v.strip().upper())
        if v not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        return v

    @field_validator("order_type")
    @classmethod
    def _order_type(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in TICKET_ORDER_TYPES:
            raise ValueError("order_type must be MARKET, LIMIT or GTT")
        return v

    @field_validator("sl_unit")
    @classmethod
    def _sl_unit(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in SL_UNITS:
            raise ValueError("sl_unit must be pct or price")
        return v

    @field_validator("trail_unit")
    @classmethod
    def _trail_unit(cls, v: str) -> str:
        v = {"points": "pts", "point": "pts"}.get(v.strip().lower(), v.strip().lower())
        if v not in TRAIL_UNITS:
            raise ValueError("trail_unit must be pct or pts")
        return v

    @field_validator("target_unit")
    @classmethod
    def _target_unit(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in TARGET_UNITS:
            raise ValueError("target_unit must be pct or price")
        return v

    @field_validator("timeframe")
    @classmethod
    def _timeframe(cls, v: str) -> str:
        code = timeframes.normalise(v)
        if code is None:
            raise ValueError(
                "timeframe must be one of " + ", ".join(data_source.TIMEFRAME_MINUTES)
            )
        return code


# The states the charts page draws: a waiting GTT, a working entry, an open position.
CHART_TRADE_STATES = {
    WatchState.GTT_PENDING,
    WatchState.ENTRY_PLACED,
    WatchState.IN_POSITION,
    WatchState.EXIT_PLACED,
}
# Underlyings whose spot is an index rather than a stock, for the combo screen.
INDEX_UNDERLYINGS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX",
}


# --------------------------------------------------------------------- factory
def create_app(
    cfg: Config | None = None,
    *,
    env_path: Path | None = None,
    config_path: Path | None = None,
) -> FastAPI:
    cfg = cfg or load_config()
    store = Store(cfg.data_dir)
    engine = Engine(cfg, build_broker(cfg), store)
    settings = SettingsManager(cfg, env_path=env_path, config_path=config_path)
    baskets = BasketStore()
    baskets.load(store.load_baskets())

    loopback_bind = cfg.server.host in LOOPBACK_HOSTS
    if not cfg.secrets.api_key and not loopback_bind:
        raise RuntimeError(
            "MATHERAN_API_KEY must be set when binding to a non-loopback address. "
            "This service can place orders; do not expose it unauthenticated."
        )
    if not cfg.secrets.api_key:
        log.warning(
            "no MATHERAN_API_KEY set - running unauthenticated on %s. Set one from the "
            "Setup tab; it is mandatory for any non-loopback bind.",
            cfg.server.host,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await engine.start()
        log.info(
            "matheran up: mode=%s broker=%s data=%s",
            cfg.mode,
            engine.broker.name,
            getattr(engine.broker, "data_source", engine.broker.name),
        )
        try:
            yield
        finally:
            await engine.stop()

    app = FastAPI(
        title="Matheran trading API",
        version="0.1.0",
        description=(
            "VWAP + RSI/EMA + Supertrend intraday engine for NSE/BSE equity and index "
            "options. Every entry waits for your explicit approval."
        ),
        lifespan=lifespan,
    )
    app.state.cfg = cfg
    app.state.engine = engine
    app.state.settings = settings
    app.state.broker_dirty = False

    async def require_key(x_api_key: str | None = Header(None, alias="X-API-Key")) -> None:
        # Read the key per request so setting it from the UI takes effect immediately.
        key = cfg.secrets.api_key
        if not key:
            return
        if not x_api_key or not secrets_mod.compare_digest(x_api_key, key):
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")

    async def require_local(request: Request) -> None:
        """Credential and config changes are only accepted from this machine."""
        peer = request.client.host if request.client else ""
        if peer in LOOPBACK_HOSTS:
            return
        raise HTTPException(
            status_code=403,
            detail="credential and config changes are only allowed from localhost",
        )

    auth = [Depends(require_key)]
    auth_local = [Depends(require_key), Depends(require_local)]

    @app.exception_handler(EngineError)
    async def _engine_error(_request: Request, exc: EngineError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(BrokerError)
    async def _broker_error(_request: Request, exc: BrokerError):
        status = 502 if exc.retryable else 400
        return JSONResponse(
            status_code=status, content={"detail": str(exc), "code": exc.code}
        )

    @app.exception_handler(ValueError)
    async def _value_error(_request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ----------------------------------------------------------------- basics
    @app.get("/health", tags=["control"])
    async def health():
        return {
            "ok": True,
            "mode": cfg.mode,
            "broker": engine.broker.name,
            "authenticated": bool(cfg.secrets.api_key),
            "ticks": engine.tick_count,
        }

    @app.get("/api/status", tags=["control"], dependencies=auth)
    async def status():
        payload = engine.status()
        try:
            payload["broker_health"] = await engine.broker.health()
        except BrokerError as exc:
            payload["broker_health"] = {"error": str(exc)}
        payload["broker_restart_required"] = app.state.broker_dirty
        payload["authenticated"] = bool(cfg.secrets.api_key)
        payload["live_orders_supported"] = engine.broker.supports_live_orders
        payload["strategy"] = {
            "timeframe_minutes": cfg.strategy.timeframe_minutes,
            "rsi_period": cfg.strategy.rsi_period,
            "rsi_signal_entry_period": cfg.strategy.rsi_signal_entry_period,
            "rsi_signal_exit_period": cfg.strategy.rsi_signal_exit_period,
            "supertrend": [cfg.strategy.supertrend_period, cfg.strategy.supertrend_factor],
            "adx_period": cfg.strategy.adx_period,
            "adx_min": cfg.strategy.adx_min,
            "entry_condition_mode": cfg.strategy.entry_condition_mode,
            "warmup_bars": cfg.strategy.warmup_bars(),
            "exit_rules": explain(effective_rules(cfg.strategy)),
        }
        payload["risk"] = {
            "stop_loss_pct": cfg.risk.stop_loss_pct,
            "target_pct": cfg.risk.target_pct,
            "place_stop_at_broker": cfg.risk.place_stop_at_broker,
            "allow_manual_buy": cfg.risk.allow_manual_buy,
            "exit_mode": cfg.risk.exit_mode,
            "trail_profit_trigger_pct": cfg.risk.trail_profit_trigger_pct,
            "trail_profit_value": cfg.risk.trail_profit_value,
            "trail_profit_unit": cfg.risk.trail_profit_unit,
            "default_product": cfg.engine.default_product,
            "max_trades_per_day": cfg.engine.max_trades_per_day,
            "max_open_positions": cfg.engine.max_open_positions,
            "square_off_time": cfg.engine.square_off_time,
            "no_new_entry_after": cfg.engine.no_new_entry_after,
        }
        payload["timeframes"] = timeframes.info()
        payload["has_exit_rules"] = bool(effective_rules(cfg.strategy))
        return payload

    # --------------------------------------------------------------- settings
    def _exit_rules_payload() -> dict:
        rows = effective_rules(cfg.strategy)
        return {
            "catalog": rules_catalog(),
            "rules": rows,
            # False while the rows are still derived from the legacy exit flags.
            "customised": cfg.strategy.exit_rules is not None,
            **explain(rows),
        }

    @app.get("/api/settings", tags=["settings"], dependencies=auth_local)
    async def get_settings():
        return {
            "credentials": settings.credential_status(),
            "config": settings.config_snapshot(),
            "exit_rules": _exit_rules_payload(),
            "broker_restart_required": app.state.broker_dirty,
            "active_broker": engine.broker.name,
            "active_data_source": getattr(engine.broker, "data_source", engine.broker.name),
            "live_orders_supported": engine.broker.supports_live_orders,
        }

    @app.post("/api/strategy/exit-rules/preview", tags=["settings"], dependencies=auth)
    async def preview_exit_rules(body: ExitRulesBody):
        """Validate exit condition rows and read them back in words, long and short.

        Nothing is saved; send the rows to /api/settings/config as strategy.exit_rules
        to apply them.
        """
        rows = normalize_rules(body.rules)
        effective = rows if rows is not None else legacy_rules(cfg.strategy)
        return {"rules": effective, "customised": rows is not None, **explain(effective)}

    @app.put("/api/settings/credentials", tags=["settings"], dependencies=auth_local)
    async def put_credentials(body: CredentialsBody):
        result = settings.save_credentials(body.values)
        if result["saved"] or result["cleared"]:
            app.state.broker_dirty = True
        return {
            **result,
            "credentials": settings.credential_status(),
            "broker_restart_required": app.state.broker_dirty,
        }

    @app.post("/api/settings/api-key/generate", tags=["settings"], dependencies=auth_local)
    async def gen_api_key():
        """Generate, store and return a key. Shown in full exactly once."""
        key = generate_api_key()
        settings.save_credentials({"MATHERAN_API_KEY": key})
        return {
            "api_key": key,
            "note": "Saved to .env and active immediately. This is the only time it is shown.",
        }

    @app.put("/api/settings/config", tags=["settings"], dependencies=auth_local)
    async def put_config(body: ConfigBody):
        if body.mode == "live" and not body.confirm_live:
            raise HTTPException(
                400,
                "live mode sends real orders to your broker; resend with confirm_live: true",
            )
        patch = body.model_dump(exclude_none=True, exclude={"confirm_live"})
        before = (cfg.mode, cfg.broker.name, cfg.broker.data_broker)
        snapshot = settings.update_config(patch)
        if (cfg.mode, cfg.broker.name, cfg.broker.data_broker) != before:
            app.state.broker_dirty = True
        return {"config": snapshot, "broker_restart_required": app.state.broker_dirty}

    @app.post("/api/settings/broker/test", tags=["settings"], dependencies=auth_local)
    async def test_broker():
        """Build a throwaway broker from the saved settings and ping it."""
        try:
            probe = build_broker(cfg)
        except BrokerError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            await probe.startup()
            return {
                "ok": True,
                "broker": probe.name,
                "data_source": getattr(probe, "data_source", probe.name),
                "live_orders_supported": probe.supports_live_orders,
                "health": await probe.health(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "broker": probe.name, "error": str(exc)}
        finally:
            await probe.shutdown()

    @app.post("/api/settings/broker/apply", tags=["settings"], dependencies=auth_local)
    async def apply_broker():
        """Rebuild the broker from saved settings and swap it into the running engine."""
        await engine.swap_broker(build_broker(cfg))
        app.state.broker_dirty = False
        return {
            "applied": True,
            "broker": engine.broker.name,
            "mode": cfg.mode,
            "data_source": getattr(engine.broker, "data_source", engine.broker.name),
            "live_orders_supported": engine.broker.supports_live_orders,
        }

    # ---------------------------------------------------------- equity watches
    @app.post("/api/watches", tags=["watches"], dependencies=auth, status_code=201)
    async def create_watch(body: CreateWatch):
        instrument = await engine.broker.resolve_equity(body.symbol, body.exchange)
        watch = await engine.add_watch(
            instrument=instrument,
            quantity=body.quantity,
            timeframe_minutes=body.timeframe_minutes,
            stop_loss_pct=body.stop_loss_pct,
            target_pct=body.target_pct,
            kind="equity",
            direction=body.direction,
            require_adx=cfg.strategy.require_adx,
            notes=body.notes,
            product=body.product,
            exit_mode=body.exit_mode,
        )
        return watch.as_dict()

    @app.get("/api/watches", tags=["watches"], dependencies=auth)
    async def list_watches():
        watches = list(engine.watches.values())
        prices = await engine._fetch_prices(watches) if watches else {}
        rows = []
        for w in watches:
            ltp = prices.get(w.instrument.security_id)
            rows.append({**w.as_dict(ltp), "ltp": ltp,
                         "effective_exit_mode": engine.exit_mode_for(w)})
        return {"count": len(watches), "watches": rows}

    @app.get("/api/watches/{watch_id}", tags=["watches"], dependencies=auth)
    async def get_watch(watch_id: str):
        watch = engine.watches.get(watch_id)
        if watch is None:
            raise HTTPException(404, f"no such watch: {watch_id}")
        return watch.as_dict()

    @app.get("/api/watches/{watch_id}/diagnostics", tags=["watches"], dependencies=auth)
    async def diagnostics(watch_id: str):
        return await engine.diagnose(watch_id)

    @app.delete("/api/watches/{watch_id}", tags=["watches"], dependencies=auth)
    async def delete_watch(watch_id: str, force: bool = Query(False)):
        await engine.remove_watch(watch_id, force=force)
        return {"removed": watch_id}

    @app.post("/api/watches/{watch_id}/pause", tags=["watches"], dependencies=auth)
    async def pause_watch(watch_id: str):
        return engine.set_paused(watch_id, True).as_dict()

    @app.post("/api/watches/{watch_id}/resume", tags=["watches"], dependencies=auth)
    async def resume_watch(watch_id: str):
        return engine.set_paused(watch_id, False).as_dict()

    @app.post("/api/watches/{watch_id}/exit", tags=["watches"], dependencies=auth)
    async def exit_watch(watch_id: str):
        return await engine.exit_now(watch_id)

    @app.post("/api/watches/{watch_id}/cancel", tags=["watches"], dependencies=auth)
    async def cancel_watch_order(watch_id: str):
        """Cancel a pending GTT, or an entry order still working at the broker.

        Anything that filled before the cancel landed becomes a managed position.
        """
        return await engine.cancel_entry(watch_id)

    @app.post("/api/watches/{watch_id}/enter", tags=["watches"], dependencies=auth)
    async def enter_watch(watch_id: str, body: BuyBody | None = None):
        """Enter now in the watch's direction, skipping the signal.

        BUY for a long watch, SELL for a short one. Every other guard still applies:
        halt, market hours, the no-new-entry cutoff and the position/day caps. In live
        mode this sends a real order.
        """
        body = body or BuyBody()
        watch = engine.watches.get(watch_id)
        if body.direction:
            side = Direction(body.direction).entry_side.value
        elif watch is not None and watch.sides in {"LONG", "SHORT"}:
            side = Direction(watch.sides).entry_side.value
        else:
            side = "BUY/SELL"
        if cfg.live and not body.confirm:
            raise HTTPException(
                400,
                f"live mode: this sends a REAL {side} order. Resend with confirm: true.",
            )
        return await engine.enter_now(
            watch_id,
            note=body.note if body.note and body.note != "manual buy" else "manual entry",
            direction=body.direction,
            order_type=body.order_type,
            limit_price=body.limit_price,
            product=body.product,
            exit_mode=body.exit_mode,
        )

    # Kept so existing clients and bookmarks do not break.
    @app.post("/api/watches/{watch_id}/buy", tags=["watches"], dependencies=auth,
              include_in_schema=False)
    async def buy_watch(watch_id: str, body: BuyBody | None = None):
        return await enter_watch(watch_id, body)

    # ---------------------------------------------------------------- options
    @app.get("/api/options/expiries", tags=["options"], dependencies=auth)
    async def option_expiries(underlying: str = Query(...)):
        listed = await engine.broker.expiries(underlying)
        return {
            "underlying": underlying.upper(),
            "expiries": listed,
            # What the chain page offers: series that have not settled yet.
            "active": active_expiries(listed),
        }

    @app.get("/api/options/underlyings", tags=["options"], dependencies=auth)
    async def option_underlyings():
        """Every underlying with listed options, indices first. Feeds the chain page."""
        src = _chart_source("broker")
        await src._warm_instruments()
        return {"underlyings": src.option_underlyings()}

    @app.get("/api/options/oichain", tags=["options"], dependencies=auth)
    async def option_oi_chain(
        underlying: str = Query(None),
        expiry: str | None = Query(None, description="YYYY-MM-DD; empty for nearest"),
        strikes: int = Query(
            8, ge=1, le=MAX_CHAIN_STRIKES_EACH_SIDE, description="Strikes each side of ATM"
        ),
        window: int = Query(
            BUILDUP_MINUTES, ge=1, le=60, description="Buildup window in minutes"
        ),
    ):
        """Calls | strike | puts around the money.

        Per contract: LTP and change on the day, OI, OI change against the previous
        session, and the price and OI move over the last `window` minutes with its
        buildup reading (long buildup, short buildup, short covering, long unwinding).
        """
        name = (underlying or cfg.options.default_underlying).upper()
        chain = await select_full_chain(
            engine.broker, name, expiry=expiry, strikes_each_side=strikes
        )
        return await oi_chain(engine.broker, chain, window_minutes=window)

    @app.get("/api/options/straddles", tags=["options"], dependencies=auth)
    async def option_straddles(
        underlying: str = Query(None),
        expiry: str | None = Query(None, description="YYYY-MM-DD; empty for nearest"),
        timeframe_minutes: int = Query(1),
    ):
        """ATM plus seven strikes on each side as paired CE+PE premiums.

        Change is against the previous session close. VWAP, EMA(21), and
        Supertrend(21, 0.618) are calculated on closed straddle candles.
        """
        from .options import STRADDLE_STRIKES_EACH_SIDE, straddle_table

        if timeframe_minutes not in timeframes.MINUTES:
            raise HTTPException(
                400,
                "unsupported timeframe. Available minutes: "
                + ", ".join(str(value) for value in timeframes.MINUTES),
            )
        name = (underlying or cfg.options.default_underlying).upper()
        chain = await select_full_chain(
            engine.broker,
            name,
            expiry=expiry,
            strikes_each_side=STRADDLE_STRIKES_EACH_SIDE,
        )
        return await straddle_table(
            engine.broker, chain, timeframe_minutes=timeframe_minutes
        )

    @app.get("/api/options/chain", tags=["options"], dependencies=auth)
    async def option_chain(
        underlying: str = Query(None),
        expiry: str | None = Query(None),
        otm: int = Query(None, ge=0, le=20),
        timeframe_minutes: int = Query(1),
        reference: str = Query("index", pattern="^(index|future)$"),
        adx_min: float | None = Query(None),
    ):
        name = (underlying or cfg.options.default_underlying).upper()
        selection = await select_chain(
            engine.broker,
            name,
            expiry=expiry or (None if cfg.options.expiry == "nearest" else cfg.options.expiry),
            otm_count=otm if otm is not None else cfg.options.otm_count,
            reference=reference,
        )
        rows = await scan_chain(
            engine.broker,
            selection,
            cfg.strategy,
            timeframe_minutes=timeframe_minutes,
            adx_min=adx_min,
        )
        table = [r.as_dict() for r in rows]
        return {
            "underlying": selection.underlying,
            "expiry": selection.expiry,
            "reference": selection.reference,
            "reference_symbol": selection.reference_symbol,
            "spot": round(selection.spot, 2),
            "atm_strike": selection.atm_strike,
            "strike_step": selection.strike_step,
            "timeframe_minutes": timeframe_minutes,
            "adx_min": adx_min if adx_min is not None else cfg.strategy.adx_min,
            "missing_legs": selection.missing,
            "expires_today": selection.expires_today,
            "rows": table,
            "above_vwap": [r["security_id"] for r in table if r["price_above_vwap"]],
            "entry_ready": [r["security_id"] for r in table if r["entry_ready"]],
        }

    async def _resolve_option(body: CreateOptionWatch):
        """Turn a request into a concrete contract plus a lot-aligned quantity."""
        instrument = None
        if body.security_id:
            getter = getattr(engine.broker, "instrument_by_security_id", None)
            if getter is not None:
                instrument = await getter("NSE_FNO", body.security_id)
                if instrument is None:
                    instrument = await getter("BSE_FNO", body.security_id)
            if instrument is None and body.underlying:
                contracts = await engine.broker.option_chain_instruments(
                    body.underlying, body.expiry
                )
                instrument = next(
                    (c for c in contracts if c.security_id == body.security_id), None
                )
            if instrument is None:
                raise HTTPException(
                    404,
                    "could not resolve that security_id; pass underlying/expiry/strike/"
                    "option_type instead",
                )
        else:
            missing = [
                f
                for f in ("underlying", "strike", "option_type")
                if getattr(body, f) is None
            ]
            if missing:
                raise HTTPException(422, f"missing fields: {missing} (or pass security_id)")
            contracts = await engine.broker.option_chain_instruments(
                body.underlying, body.expiry
            )
            if not body.expiry:
                # Skip a series that has already settled, same rule the scanner uses.
                live = active_expiries([c.expiry for c in contracts if c.expiry])
                chosen = live[0] if live else None
                contracts = [c for c in contracts if c.expiry == chosen]
            instrument = next(
                (
                    c
                    for c in contracts
                    if c.option_type == body.option_type
                    and c.strike is not None
                    and abs(c.strike - body.strike) < 1e-6
                ),
                None,
            )
            if instrument is None:
                raise HTTPException(
                    404,
                    f"no {body.underlying} {body.strike:.0f} {body.option_type} contract "
                    f"for expiry {body.expiry or 'nearest'}",
                )

        if body.lots is not None:
            quantity = body.lots * instrument.lot_size
        elif body.quantity is not None:
            quantity = body.quantity
        else:
            raise HTTPException(422, "pass either lots or quantity")
        return instrument, quantity

    async def _add_option_watch(body: CreateOptionWatch):
        instrument, quantity = await _resolve_option(body)
        return await engine.add_watch(
            instrument=instrument,
            quantity=quantity,
            timeframe_minutes=body.timeframe_minutes,
            stop_loss_pct=body.stop_loss_pct,
            target_pct=body.target_pct,
            kind="option",
            require_adx=True,
            adx_min=body.adx_min,
            notes=body.notes,
            product=body.product,
            exit_mode=body.exit_mode,
        )

    @app.post("/api/options/watches", tags=["options"], dependencies=auth, status_code=201)
    async def create_option_watch(body: CreateOptionWatch):
        watch = await _add_option_watch(body)
        return watch.as_dict()

    @app.post("/api/options/buy", tags=["options"], dependencies=auth, status_code=201)
    async def buy_option(body: OptionBuyBody):
        """Start watching a contract and buy it straight away.

        Used by the Buy button on the options table. If the contract is already being
        watched, the existing watch is reused rather than rejected.
        """
        if cfg.live and not body.confirm:
            raise HTTPException(
                400, "live mode: this sends a REAL buy order. Resend with confirm: true."
            )
        try:
            watch = await _add_option_watch(body)
        except EngineError as exc:
            if "already being watched" not in str(exc):
                raise
            instrument, _ = await _resolve_option(body)
            watch = next(
                (
                    w
                    for w in engine.watches.values()
                    if w.instrument.security_id == instrument.security_id
                    and w.instrument.segment == instrument.segment
                ),
                None,
            )
            if watch is None:
                raise
        return await engine.enter_now(
            watch.id,
            note=body.notes or "manual entry from options",
            order_type=body.order_type,
            limit_price=body.limit_price,
            product=body.product,
            exit_mode=body.exit_mode,
        )

    # ---------------------------------------------------------------- baskets
    def _persist_baskets() -> None:
        store.save_baskets(baskets.to_list())

    async def _leg_instrument(symbol: str):
        """Resolve a chart symbol id into a tradable instrument."""
        source = _chart_source("broker")
        return await source._resolve(symbol)

    def _leg_watch(leg):
        return engine.watches.get(leg.watch_id or "")

    def _leg_busy(watch) -> bool:
        return watch is not None and (watch.position is not None or watch.state in ACTIVE_STATES)

    def _basket_view(
        basket, prices: dict[str, float], trades: list[dict], unwatched: dict | None = None
    ) -> dict:
        """A basket with each leg's live state, and totals across the legs.

        `unwatched` maps a leg symbol to its instrument for legs with no watch yet (a
        basket never armed or executed), so their prices still show.
        """
        unwatched = unwatched or {}
        data = basket.as_dict()
        legs_out = []
        unrealised = 0.0
        value_now = 0.0
        priced = 0
        open_legs = in_flight = 0
        watch_ids: set[str] = set()
        # Premium in points, as the basket chart draws it: lots reduced by their common
        # divisor, so equal lots read as the plain sum or difference of the prices.
        lots = []
        for leg in basket.legs:
            watch = _leg_watch(leg)
            inst = watch.instrument if watch is not None else unwatched.get(leg.symbol)
            lot = max(1, int(inst.lot_size or 1)) if inst is not None else 1
            lots.append(leg.quantity / lot)
        weights = unit_weights(lots)
        premium = 0.0
        for leg, weight in zip(basket.legs, weights):
            watch = _leg_watch(leg)
            inst = watch.instrument if watch is not None else unwatched.get(leg.symbol)
            ltp = prices.get(inst.security_id) if inst is not None else None
            if watch is not None:
                watch_ids.add(watch.id)
                if watch.position is not None:
                    open_legs += 1
                    unrealised += watch.position.unrealised(ltp)
                elif watch.state in ACTIVE_STATES:
                    in_flight += 1
            if ltp is not None:
                value_now += leg.sign * leg.quantity * ltp
                premium += leg.sign * weight * ltp
                priced += 1
            legs_out.append(
                {**leg.as_dict(), "ltp": ltp, "lots": lots[len(legs_out)],
                 "watch": watch.as_dict(ltp) if watch else None}
            )

        since = basket.created_at.isoformat()
        realised = sum(
            float(t.get("pnl", 0.0))
            for t in trades
            if t.get("watch_id") in watch_ids and str(t.get("exit_time", "")) >= since
        )
        if open_legs or in_flight:
            status = "open"
        elif basket.state in {"executed", "closed"}:
            status = "closed"
        elif watch_ids:
            status = "watching" if any(
                not engine.watches[w].manual_only for w in watch_ids
            ) else "ready"
        else:
            status = "draft"

        data.update(
            legs=legs_out,
            status=status,
            open_legs=open_legs,
            in_flight_legs=in_flight,
            # A hedged basket with a leg missing is a different, riskier position.
            partial=0 < open_legs < len(basket.legs),
            unrealised_pnl=round(unrealised, 2),
            realised_pnl=round(realised, 2),
            value_now=round(value_now, 2) if priced == len(basket.legs) else None,
            premium_now=round(premium, 2) if priced == len(basket.legs) else None,
        )
        return data

    @app.get("/api/baskets", tags=["baskets"], dependencies=auth)
    async def list_baskets():
        items = baskets.all()
        watches = [w for b in items for w in map(_leg_watch, b.legs) if w is not None]
        # Legs of baskets not armed or executed yet have no watch; their instruments are
        # resolved so the card can still show prices and the premium.
        unwatched: dict = {}
        for b in items:
            for leg in b.legs:
                if _leg_watch(leg) is None and leg.symbol not in unwatched:
                    try:
                        unwatched[leg.symbol] = await _leg_instrument(leg.symbol)
                    except BrokerError:
                        pass
        prices: dict[str, float] = {}
        if watches:
            prices.update(await engine._fetch_prices(watches))
        if unwatched:
            try:
                quotes = await engine.broker.ltp(list(unwatched.values()))
                prices.update({k: v for k, v in quotes.items() if v and v > 0})
            except BrokerError as exc:
                log.warning("baskets: could not price unarmed legs: %s", exc)
        trades = store.load_trades(2000) if watches else []
        rows = [_basket_view(b, prices, trades, unwatched) for b in items]
        return {"count": len(rows), "baskets": rows}

    @app.post("/api/baskets", tags=["baskets"], dependencies=auth, status_code=201)
    async def create_basket(body: CreateBasket):
        # Resolve and validate every leg before storing anything, so a basket is never
        # half-valid. Lots are turned into units here, with the contract's real lot
        # size, so an unusable quantity surfaces now rather than at execution.
        legs: list[BasketLeg] = []
        for item in body.legs:
            symbol = item.symbol if ":" in item.symbol else f"eq:NSE:{item.symbol.upper()}"
            instrument = await _leg_instrument(symbol)
            lot = max(1, int(instrument.lot_size or 1))
            if item.lots is not None:
                quantity = item.lots * lot
            elif item.quantity is not None:
                quantity = item.quantity
            else:
                raise HTTPException(422, f"leg {symbol}: pass lots or quantity")
            if lot > 1 and quantity % lot != 0:
                raise HTTPException(
                    400,
                    f"{instrument.symbol} trades in lots of {lot}; leg quantity {quantity} "
                    f"is not a multiple. Nearest: {max(1, round(quantity / lot)) * lot}.",
                )
            legs.append(
                BasketLeg(
                    symbol=symbol,
                    direction=Direction(item.direction),
                    quantity=quantity,
                    label=item.label.strip() or instrument.symbol,
                )
            )
        basket = baskets.create(
            name=body.name,
            legs=legs,
            timeframe_minutes=body.timeframe_minutes,
            stop_loss_pct=body.stop_loss_pct,
            target_pct=body.target_pct,
            notes=body.notes,
            product=body.product or cfg.engine.default_product,
            exit_mode=body.exit_mode or "",
        )
        _persist_baskets()
        return basket.as_dict()

    @app.delete("/api/baskets/{basket_id}", tags=["baskets"], dependencies=auth)
    async def delete_basket(basket_id: str, force: bool = Query(False)):
        basket = baskets.get(basket_id)
        live = [leg for leg in basket.legs if _leg_busy(_leg_watch(leg))]
        if live and not force:
            raise HTTPException(
                400,
                f"{len(live)} leg(s) still hold a position or have an order in flight. "
                "Exit the basket first, or pass force=true to forget the grouping and "
                "manage the legs individually.",
            )
        for leg in basket.legs:
            watch = _leg_watch(leg)
            if watch is None:
                continue
            if live:
                # Forced: the legs carry on as ordinary watches, still protected.
                watch.basket_id = None
                continue
            try:
                await engine.remove_watch(watch.id)
            except EngineError:
                pass
        engine._persist()
        baskets.remove(basket_id)
        _persist_baskets()
        return {"removed": basket_id}

    async def _ensure_leg_watches(basket, *, manual_only: bool) -> tuple[list[str], list[str]]:
        """A watch per leg: created on first use, re-used afterwards.

        Every leg is resolved and checked before any watch is created, so a conflict
        on the third leg cannot leave the first two half set up.
        """
        pending = []
        for leg in basket.legs:
            if _leg_watch(leg) is not None:
                continue
            instrument = await _leg_instrument(leg.symbol)
            existing = next(
                (
                    w for w in engine.watches.values()
                    if w.instrument.security_id == instrument.security_id
                    and w.instrument.segment == instrument.segment
                ),
                None,
            )
            if existing is not None and existing.basket_id != basket.id:
                # Re-using it would trade that watch's direction and quantity, not the
                # leg's, so refuse rather than guess.
                raise HTTPException(
                    409,
                    f"{instrument.symbol} is already watched separately (watch "
                    f"{existing.id}). Remove that watch first so this leg trades its own "
                    f"{leg.direction.entry_side.value} {leg.quantity}.",
                )
            pending.append((leg, instrument, existing))

        created, reused = [], []
        for leg in basket.legs:
            watch = _leg_watch(leg)
            if watch is not None:
                reused.append(watch.id)
        for leg, instrument, existing in pending:
            if existing is not None:
                leg.watch_id = existing.id
                reused.append(existing.id)
                continue
            watch = await engine.add_watch(
                instrument=instrument,
                quantity=leg.quantity,
                timeframe_minutes=basket.timeframe_minutes,
                stop_loss_pct=basket.stop_loss_pct,
                target_pct=basket.target_pct,
                kind="option" if instrument.is_option else "equity",
                direction=leg.direction,
                basket_id=basket.id,
                manual_only=manual_only,
                require_adx=instrument.is_option,
                notes=f"{basket.name}: {leg.label or leg.symbol}",
                product=basket.product,
                exit_mode=basket.exit_mode or None,
            )
            leg.watch_id = watch.id
            created.append(watch.id)

        for leg in basket.legs:
            watch = _leg_watch(leg)
            if watch is not None:
                watch.manual_only = manual_only
        engine._persist()
        return created, reused

    @app.post("/api/baskets/{basket_id}/arm", tags=["baskets"], dependencies=auth)
    async def arm_basket(basket_id: str):
        """Watch every leg for its own entry signal. Nothing is ordered now.

        Each leg then behaves like any other watch - its own conditions, its own
        approval card, its own stop and exits.
        """
        basket = baskets.get(basket_id)
        created, reused = await _ensure_leg_watches(basket, manual_only=False)
        basket.state = "armed"
        _persist_baskets()
        return {"basket": basket.as_dict(), "armed": created, "reused": reused}

    @app.post("/api/baskets/{basket_id}/disarm", tags=["baskets"], dependencies=auth)
    async def disarm_basket(basket_id: str):
        """Stop the legs raising their own approvals. Open legs keep their exits."""
        basket = baskets.get(basket_id)
        for leg in basket.legs:
            watch = _leg_watch(leg)
            if watch is None:
                continue
            watch.manual_only = True
            if watch.approval_id:
                approval = engine.approvals.get(watch.approval_id)
                if approval is not None and approval.status == "pending":
                    await engine.reject(approval.id, "basket stopped watching")
        engine._persist()
        if basket.state == "armed":
            basket.state = "draft"
        _persist_baskets()
        return {"basket": basket.as_dict()}

    @app.post("/api/baskets/{basket_id}/execute", tags=["baskets"], dependencies=auth)
    async def execute_basket(basket_id: str, body: ExecuteBasketBody | None = None):
        """Enter every leg now, skipping the signals.

        Everything that would stop a leg part-way - halt, market hours, the position
        cap, a leg already open - is checked before the first order, because a hedged
        basket with a leg missing is a different and riskier position. Bought legs go
        first so the hedge is in place before the sold legs need margin. Legs are then
        attempted independently and each is reported, so a broker-side failure is
        visible rather than silent.

        `order_type` LIMIT sends every leg as a limit order at its price in
        `limit_prices`; each rests until its own price comes, so the legs can fill at
        different times. `product` and `exit_mode` default to the basket's own.
        """
        body = body or ExecuteBasketBody()
        basket = baskets.get(basket_id)
        product = body.product or basket.product or cfg.engine.default_product
        prices = {str(k): float(v) for k, v in (body.limit_prices or {}).items()}
        if body.order_type == "LIMIT":
            missing = [leg.label or leg.symbol for leg in basket.legs
                       if not prices.get(leg.symbol) or prices[leg.symbol] <= 0]
            if missing:
                raise HTTPException(
                    400, "a limit basket needs a limit price for every leg; missing: "
                    + ", ".join(missing) + ". No leg was sent.",
                )
        if cfg.live and not body.confirm:
            raise HTTPException(
                400,
                f"live mode: this sends {len(basket.legs)} REAL orders. "
                "Resend with confirm: true.",
            )
        if not cfg.risk.allow_manual_buy:
            raise HTTPException(
                400, "manual entry is disabled (risk.allow_manual_buy); no leg was sent"
            )
        busy = [leg.label or leg.symbol for leg in basket.legs if _leg_busy(_leg_watch(leg))]
        if busy:
            raise HTTPException(
                400,
                "these legs are already open or have an order in flight: "
                + ", ".join(busy) + ". Exit the basket first.",
            )
        blocked = engine.entry_block_reason(len(basket.legs), product)
        if blocked:
            raise HTTPException(400, f"cannot execute: {blocked}. No leg was sent.")

        await _ensure_leg_watches(basket, manual_only=True)
        for leg in basket.legs:
            leg_watch = _leg_watch(leg)
            try:
                engine._check_trade_settings(
                    leg_watch.instrument, leg.direction.value, product,
                    body.exit_mode or engine.exit_mode_for(leg_watch),
                )
            except EngineError as exc:
                raise HTTPException(
                    400, f"{leg.label or leg.symbol}: {exc}. No leg was sent."
                ) from exc
        capped = [
            leg.label or leg.symbol for leg in basket.legs
            if _leg_watch(leg).trades_today >= cfg.engine.max_trades_per_day
        ]
        if capped:
            raise HTTPException(
                400,
                f"max_trades_per_day ({cfg.engine.max_trades_per_day}) already reached for "
                + ", ".join(capped) + ". No leg was sent.",
            )

        results = []
        ordered = sorted(basket.legs, key=lambda l: 0 if l.direction is Direction.LONG else 1)
        for leg in ordered:
            entry = {"symbol": leg.symbol, "label": leg.label,
                     "side": leg.direction.entry_side.value,
                     "quantity": leg.quantity, "watch_id": leg.watch_id,
                     "order_type": body.order_type,
                     "limit_price": prices.get(leg.symbol) if body.order_type == "LIMIT" else None}
            try:
                await engine.enter_now(
                    leg.watch_id,
                    note=f"basket {basket.name}",
                    direction=leg.direction,
                    order_type=body.order_type,
                    limit_price=prices.get(leg.symbol),
                    product=product,
                    exit_mode=body.exit_mode,
                )
                entry["status"] = "sent"
            except (EngineError, BrokerError) as exc:
                entry["status"] = "failed"
                entry["error"] = str(exc)
            results.append(entry)

        sent = sum(1 for r in results if r["status"] == "sent")
        basket.state = "executed" if sent else "draft"
        _persist_baskets()
        if sent and sent < len(results):
            log.error(
                "baskets: %s partially executed - %d of %d legs sent",
                basket.id, sent, len(results),
            )
        return {
            "basket": basket.as_dict(),
            "legs": results,
            "sent": sent,
            "failed": len(results) - sent,
            "partial": 0 < sent < len(results),
            "mode": cfg.mode,
            "order_type": body.order_type,
            "product": product,
        }

    @app.post("/api/baskets/{basket_id}/exit", tags=["baskets"], dependencies=auth)
    async def exit_basket(basket_id: str):
        """Close every leg that currently holds a position.

        Sold legs are bought back first, so the basket is never left short without
        its hedge while the orders go through.
        """
        basket = baskets.get(basket_id)
        results = []
        ordered = sorted(basket.legs, key=lambda l: 0 if l.direction is Direction.SHORT else 1)
        for leg in ordered:
            watch = _leg_watch(leg)
            row = {"symbol": leg.symbol, "label": leg.label}
            if watch is not None and watch.state is WatchState.EXIT_PLACED:
                results.append({**row, "status": "exit already in flight"})
                continue
            if watch is not None and watch.state is WatchState.ENTRY_PLACED:
                results.append({**row, "status": "failed",
                                "error": "entry order still in flight; exit once it fills"})
                continue
            if watch is None or watch.position is None:
                results.append({**row, "status": "flat"})
                continue
            try:
                await engine.exit_now(watch.id)
                results.append({**row, "status": "exiting"})
            except (EngineError, BrokerError) as exc:
                results.append({**row, "status": "failed", "error": str(exc)})
        if all(r["status"] != "failed" for r in results):
            basket.state = "closed"
        _persist_baskets()
        return {"basket": basket.as_dict(), "legs": results}

    # -------------------------------------------------------------- approvals
    @app.get("/api/approvals", tags=["approvals"], dependencies=auth)
    async def list_approvals(include_decided: bool = Query(False)):
        items = (
            list(engine.approvals.values()) if include_decided else engine.pending_approvals()
        )
        items.sort(key=lambda a: a.created_at, reverse=True)
        return {"count": len(items), "approvals": [a.as_dict() for a in items]}

    @app.post("/api/approvals/{approval_id}/approve", tags=["approvals"], dependencies=auth)
    async def approve(approval_id: str):
        return await engine.approve(approval_id)

    @app.post("/api/approvals/{approval_id}/reject", tags=["approvals"], dependencies=auth)
    async def reject(approval_id: str, body: RejectBody | None = None):
        return await engine.reject(approval_id, body.note if body else "")

    # ------------------------------------------------------- trades/positions
    @app.get("/api/trades", tags=["reports"], dependencies=auth)
    async def trades(limit: int = Query(200, ge=1, le=5000)):
        rows = store.load_trades(limit)
        realised = sum(r.get("pnl", 0.0) for r in rows)
        wins = sum(1 for r in rows if r.get("pnl", 0.0) > 0)
        return {
            "count": len(rows),
            "realised_pnl": round(realised, 2),
            "wins": wins,
            "losses": len(rows) - wins,
            "trades": rows,
        }

    @app.get("/api/positions", tags=["reports"], dependencies=auth)
    async def positions():
        watches = [w for w in engine.watches.values() if w.position is not None]
        prices = await engine._fetch_prices(watches) if watches else {}
        engine_side = [
            {
                "watch_id": w.id,
                **w.position.as_dict(prices.get(w.instrument.security_id)),
            }
            for w in watches
        ]
        out = {"engine_positions": engine_side}
        try:
            out["broker_positions"] = [
                {
                    "security_id": p.security_id,
                    "segment": p.segment,
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "average_price": p.average_price,
                }
                for p in await engine.broker.positions()
            ]
        except BrokerError as exc:
            out["broker_positions_error"] = str(exc)
        return out

    # ---------------------------------------------------------------- control
    @app.post("/api/control/halt", tags=["control"], dependencies=auth)
    async def halt(body: HaltBody | None = None):
        body = body or HaltBody()
        return await engine.halt(square_off=body.square_off, reason=body.reason)

    @app.post("/api/control/resume", tags=["control"], dependencies=auth)
    async def resume():
        return engine.resume()

    @app.post("/api/control/tick", tags=["control"], dependencies=auth)
    async def force_tick():
        await engine.tick()
        return engine.status()

    # ----------------------------------------------------------------- charts
    # One source instance per registered provider, built on first use. The broker
    # source is rebuilt whenever the engine swaps brokers so charts never serve
    # candles from a broker that is no longer in use.
    chart_sources: dict[str, object] = {}
    chart_source_broker: dict[str, object] = {}

    def _chart_source(name: str):
        current = engine.broker
        if name in chart_sources and chart_source_broker.get(name) is current:
            return chart_sources[name]
        source = data_source.build(name, broker=current, baskets=baskets)
        chart_sources[name] = source
        chart_source_broker[name] = current
        return source

    @app.get("/api/charts/sources", tags=["charts"], dependencies=auth)
    async def chart_sources_list():
        return {
            "sources": data_source.available(),
            "timeframes": [t for t, _ in data_source.TIMEFRAMES],
            "timeframe_info": timeframes.info(),
            "chart_types": [
                {"id": "candles", "label": "Candles"},
                {"id": "heikin_ashi", "label": "Heikin Ashi"},
                {"id": "renko", "label": "Renko"},
            ],
            "active_data_source": getattr(engine.broker, "data_source", engine.broker.name),
            "indicators": chart_indicators.catalog(cfg.strategy),
            "default_indicators": chart_indicators.DEFAULT_IDS,
        }

    @app.get("/api/charts/symbols", tags=["charts"], dependencies=auth)
    async def chart_symbols(
        q: str = Query("", description="Filter text; empty returns defaults"),
        source: str = Query("broker"),
        limit: int = Query(200, ge=1, le=1000),
    ):
        src = _chart_source(source)
        found = await src.search(q, limit)
        return {"source": source, "count": len(found), "symbols": [s.as_dict() for s in found]}

    @app.get("/api/charts/candles", tags=["charts"], dependencies=auth)
    async def chart_candles(
        symbol: str = Query(..., description="Symbol id from /api/charts/symbols"),
        timeframe: str = Query("5m"),
        source: str = Query("broker"),
        bars: int = Query(data_source.DEFAULT_BARS, ge=10, le=5000),
        indicators: str | None = Query(
            None, description="Comma-separated indicator ids from /api/charts/sources"
        ),
        chart_type: str = Query(
            "candles", pattern="^(candles|heikin_ashi|renko)$",
            description="candles, heikin_ashi, or renko (bricks of `box`)",
        ),
        box: float | None = Query(
            None, gt=0, description="Renko box size in price; blank = ATR(14) of the timeframe"
        ),
        params: str | None = Query(
            None,
            description='Indicator parameters as JSON, e.g. {"zema_slow": {"period": 200}, '
            '"st_tf2": {"tf": "1h", "period": 10, "factor": 3}}',
        ),
    ):
        # Validated here rather than inside each provider, so a newly added source
        # cannot forget to do it.
        code = timeframes.normalise(timeframe)
        if code is None:
            raise HTTPException(
                400,
                f"unsupported timeframe '{timeframe}'. Available: "
                f"{', '.join(data_source.TIMEFRAME_MINUTES)}",
            )
        minutes = timeframes.CODE_MINUTES[code]
        wanted: list[str] = []
        if indicators is not None:
            wanted = [i.strip() for i in indicators.split(",") if i.strip()]
            unknown = [i for i in wanted if i not in chart_indicators.CATALOG_IDS]
            if unknown:
                raise HTTPException(
                    400,
                    f"unknown indicators {unknown}. Available: "
                    f"{sorted(chart_indicators.CATALOG_IDS)}",
                )
        try:
            ind_params = chart_indicators.parse_params(params)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        src = _chart_source(source)
        info: dict = {}
        meta = getattr(src, "meta", None)
        if meta is not None:
            try:
                info = await meta(symbol)
            except BrokerError:
                info = {}
        segment = str(info.get("segment") or "NSE_EQ")
        tick = float(info.get("tick_size") or 0.05)

        # Bars before the first one shown, so indicator lines start settled, Heikin
        # Ashi's recursion has run in, and Renko has history to build bricks from.
        warm = chart_indicators.warmup_bars(cfg.strategy, wanted, ind_params) if wanted else 0
        if chart_type == "heikin_ashi":
            warm = max(warm, 50)
        fetch = bars + warm if chart_type != "renko" else max(2 * bars, bars + warm)
        rows = await src.candles(symbol, code, min(5000, fetch))

        payload: dict = {
            "symbol": symbol,
            "timeframe": code,
            "timeframe_minutes": minutes,
            "source": source,
            "chart_type": chart_type,
        }
        if info:
            payload["name"] = info.get("display_name")
            payload["meta"] = info
        if not rows:
            payload.update(count=0, bars=[])
            if indicators is not None:
                payload["indicators"] = {}
            return payload

        if chart_type == "heikin_ashi":
            # Indicators stay on the real prices, which are what the engine trades.
            shown, base = chart_types.heikin_ashi(rows), rows
        elif chart_type == "renko":
            size = float(box) if box else chart_types.atr_box(rows, 14, tick)
            shown = chart_types.renko(rows, size)
            base = shown
            payload["box"] = size
        else:
            shown, base = rows, rows

        if indicators is not None:
            other: dict[str, list] = {}
            if chart_type != "renko":
                for other_code in chart_indicators.other_timeframes(wanted, ind_params, code):
                    other_minutes = timeframes.CODE_MINUTES[other_code]
                    need = int(len(base) * minutes / other_minutes) + 60
                    try:
                        other[other_code] = await src.candles(
                            symbol, other_code, max(100, min(5000, need))
                        )
                    except BrokerError:
                        other[other_code] = []
            series = chart_indicators.compute(
                base, cfg.strategy, wanted, params=ind_params, other=other,
                minutes=minutes, segment=segment,
            )

        shown = shown[-bars:]
        first = shown[0].time if shown else 0
        payload["count"] = len(shown)
        payload["bars"] = [b.as_dict() for b in shown]
        if indicators is not None:
            payload["indicators"] = {
                key: [p for p in points if p["time"] >= first] for key, points in series.items()
            }

        # The real last price (a Heikin Ashi close is an average) and when the bar now
        # forming closes, for the countdown on the price axis.
        last, prev = rows[-1], rows[-2] if len(rows) > 1 else rows[-1]
        now = now_ist()
        closes = bar_end(datetime.fromtimestamp(last.time, IST), minutes, segment)
        payload["last_price"] = last.close
        payload["prev_price"] = prev.close
        payload["clock"] = {
            "bar_close": int(closes.timestamp()),
            "server_time": round(now.timestamp(), 3),
            "session_open": int(session_open(segment, now.date()).timestamp()),
            "session_close": int(session_close(segment, now.date()).timestamp()),
            "trading_day": now.weekday() < 5,
        }
        return payload

    @app.post("/api/charts/trade", tags=["charts"], dependencies=auth, status_code=201)
    async def chart_trade(body: ChartTradeBody):
        """Place a manual order from a chart pane: market, limit, or GTT.

        The order carries its own stop (price or %), trailing stop (points or %) and
        target (price or %), and by default also closes on the Strategy tab's exit
        conditions, read on the chart's timeframe. A GTT is held by the engine and fires
        when the live price reaches the trigger, so the app must be running for it.
        Halt, market hours, the no-new-entry cutoff and the position caps all apply.
        """
        kind, _, _rest = body.symbol.partition(":")
        if kind == "idx":
            raise HTTPException(
                400, "an index spot cannot be traded; chart its future or an option instead"
            )
        if kind == "basket":
            raise HTTPException(400, "a basket is executed from the Baskets tab")
        if cfg.live and not body.confirm:
            raise HTTPException(
                400,
                f"live mode: this sends a REAL {body.side} order. Resend with confirm: true.",
            )
        symbol = body.symbol if ":" in body.symbol else f"eq:NSE:{body.symbol.upper()}"
        instrument = await _chart_source("broker")._resolve(symbol)
        if instrument.instrument_type == "INDEX" or instrument.segment == "IDX_I":
            raise HTTPException(400, "an index cannot be traded directly")
        lot = max(1, int(instrument.lot_size or 1))
        if body.lots is not None:
            quantity = body.lots * lot
        elif body.quantity is not None:
            quantity = body.quantity
        else:
            raise HTTPException(422, "pass lots or quantity")
        exit_mode = body.exit_mode or ("sl_target" if body.use_exit_rules is False else "both")
        ticket = TradeTicket(
            direction=Direction.LONG if body.side == "BUY" else Direction.SHORT,
            quantity=quantity,
            order_type=body.order_type,
            limit_price=body.limit_price,
            trigger_price=body.trigger_price,
            sl_value=body.sl_value,
            sl_unit=body.sl_unit,
            trail_value=body.trail_value,
            trail_unit=body.trail_unit,
            trail_trigger_pct=body.trail_trigger_pct,
            target_value=body.target_value,
            target_unit=body.target_unit,
            exit_mode=exit_mode,
            product=body.product or cfg.engine.default_product,
            note=body.note.strip() or "manual order from the charts page",
        )
        return await engine.place_ticket(
            instrument=instrument,
            ticket=ticket,
            timeframe_minutes=timeframes.CODE_MINUTES[body.timeframe],
            kind="option" if instrument.is_option else "equity",
            chart_symbol=symbol,
        )

    @app.get("/api/charts/trades", tags=["charts"], dependencies=auth)
    async def chart_trades():
        """What to draw on the charts: pending GTTs, working entries, open positions.

        Makes no quote call - the charts already hold the latest price in their candles.
        """
        rows = []
        for w in engine.watches.values():
            if w.state not in CHART_TRADE_STATES:
                continue
            ids = {w.chart_symbol, data_source.chart_symbol_for(w.instrument)} - {""}
            rows.append({
                "watch_id": w.id,
                "symbols": sorted(ids),
                "label": w.instrument.symbol,
                "state": w.state.value,
                "direction": w.direction.value,
                "side": w.direction.entry_side.value,
                "basket_id": w.basket_id,
                "lot_size": w.instrument.lot_size,
                "ticket": w.ticket.as_dict() if w.ticket else None,
                "entry_order": w.entry_order.as_dict() if w.entry_order else None,
                "position": w.position.as_dict() if w.position else None,
                "notes": w.notes,
                "last_error": w.last_error,
            })
        return {"mode": cfg.mode, "count": len(rows), "trades": rows}

    @app.get("/api/combo", tags=["charts"], dependencies=auth)
    async def combo_chart(
        basket: str | None = Query(None, description="Saved basket id"),
        legs: str | None = Query(
            None,
            description="Unsaved legs instead: symbol@BUY|SELL@lots, comma separated, e.g. "
            "opt:NIFTY:2026-10-06:25000:CE@BUY@1,opt:NIFTY:2026-10-06:25000:PE@BUY@1",
        ),
        timeframe: str = Query("5m"),
        bars: int = Query(data_source.DEFAULT_BARS, ge=10, le=5000),
        bar_range: str = Query(
            "spot", alias="range", pattern="^(spot|body|wicks)$",
            description="spot = spot linked (recommended), body = no wicks, wicks = sum of leg wicks",
        ),
        cp: str = Query("abs", pattern="^(abs|net)$",
                        description="Call/put baskets as absolute or signed values"),
        ema1: int = Query(9, ge=1, le=500),
        ema2: int = Query(21, ge=1, le=500),
        st_factor: float = Query(3.0, gt=0, le=50),
        st_atr: int = Query(10, ge=1, le=500),
        spot: str | None = Query(
            None, description="Chart symbol for the underlying pane; default: the options' underlying"
        ),
    ):
        """A basket as the TradingView combo script draws it: the underlying, the
        combined premium with VWAP / EMA / Supertrend, the call legs and the put legs.

        Legs are weighted by lots, reduced by their common divisor, so the charts read in
        premium points. See combo.py for the arithmetic and its bar-range modes.
        """
        code = timeframes.normalise(timeframe)
        if code is None:
            raise HTTPException(
                400, f"unsupported timeframe '{timeframe}'. Available: "
                f"{', '.join(data_source.TIMEFRAME_MINUTES)}"
            )
        timeframe = code
        # (symbol, direction, lots or None, units or None, label, watch_id)
        specs: list[tuple] = []
        name = "unsaved legs"
        if basket:
            chosen = baskets.get(basket)
            name = chosen.name
            for leg in chosen.legs:
                specs.append((leg.symbol, leg.direction, None, leg.quantity, leg.label, leg.watch_id))
        elif legs:
            for part in legs.split(","):
                part = part.strip()
                if not part:
                    continue
                sym, _, rest = part.partition("@")
                side, _, lots_text = rest.partition("@")
                side = side.strip().upper()
                if side not in {"", "BUY", "SELL", "B", "S", "LONG", "SHORT"}:
                    raise HTTPException(400, f"leg '{part}': side must be BUY or SELL")
                try:
                    weight = float(lots_text) if lots_text.strip() else 1.0
                except ValueError:
                    raise HTTPException(400, f"leg '{part}': lots must be a number") from None
                if weight <= 0:
                    raise HTTPException(400, f"leg '{part}': lots must be positive")
                direction = Direction.SHORT if side in {"SELL", "S", "SHORT"} else Direction.LONG
                specs.append((sym.strip(), direction, weight, None, "", None))
        else:
            raise HTTPException(400, "pass basket=<id>, or legs=symbol@BUY|SELL@lots,...")
        if not specs:
            raise HTTPException(400, "no legs to chart")
        if len(specs) > 10:
            raise HTTPException(400, "a combo is limited to 10 legs")

        src = _chart_source("broker")

        async def resolve(symbol: str):
            try:
                return await src._resolve(symbol), ""
            except BrokerError as exc:
                return None, str(exc)

        async def fetch(symbol: str):
            try:
                return await src.candles(symbol, timeframe, bars), ""
            except BrokerError as exc:
                return [], str(exc)

        resolved, fetched = await asyncio.gather(
            asyncio.gather(*(resolve(s[0]) for s in specs)),
            asyncio.gather(*(fetch(s[0]) for s in specs)),
        )

        combo_legs: list[ComboLeg] = []
        leg_bars = []
        for spec, (inst, resolve_error), (rows, fetch_error) in zip(specs, resolved, fetched):
            symbol, direction, weight, units, label, watch_id = spec
            lot = max(1, int(inst.lot_size or 1)) if inst is not None else 1
            if weight is None:
                weight = (units or 0) / lot
            watch = engine.watches.get(watch_id or "")
            entry = (
                watch.position.entry_price
                if watch is not None and watch.position is not None else None
            )
            option_type = inst.option_type if inst is not None else None
            combo_legs.append(ComboLeg(
                symbol=symbol,
                label=label or (inst.symbol if inst is not None else symbol),
                sign=direction.sign,
                lots=float(weight),
                option_type=option_type if option_type in ("CE", "PE") else None,
                lot_size=lot,
                strike=inst.strike if inst is not None else None,
                expiry=inst.expiry if inst is not None else None,
                entry=entry,
                error=resolve_error or fetch_error or ("" if rows else "no candles"),
            ))
            leg_bars.append(rows)

        underlyings = sorted({
            inst.underlying.upper()
            for inst, _ in resolved
            if inst is not None and inst.is_option and inst.underlying
        })
        spot_note = ""
        if spot:
            spot_symbol = spot
        elif underlyings:
            und = underlyings[0]
            spot_symbol = f"idx:{und}" if und in INDEX_UNDERLYINGS else f"eq:NSE:{und}"
            if len(underlyings) > 1:
                spot_note = "legs on several underlyings; showing " + und
        else:
            spot_symbol = "idx:NIFTY"
            spot_note = "no option legs; showing NIFTY as the market reference"

        spot_payload: dict = {"symbol": spot_symbol, "bars": [], "indicators": {},
                              "error": "", "note": spot_note}
        try:
            spot_bars = await src.candles(spot_symbol, timeframe, bars)
            spot_payload["bars"] = [b.as_dict() for b in spot_bars]
            spot_payload["indicators"] = chart_indicators.compute(
                spot_bars, cfg.strategy, ["vwap", "ema_price", "supertrend"]
            )
        except BrokerError as exc:
            spot_payload["error"] = str(exc)

        payload = build_combo(
            combo_legs, leg_bars, mode=bar_range, absolute=cp == "abs",
            ema1=ema1, ema2=ema2, st_factor=st_factor, st_atr=st_atr,
        )
        return {
            "name": name,
            "basket_id": basket,
            "timeframe": timeframe,
            "range": bar_range,
            "cp": cp,
            "underlying": underlyings[0] if len(underlyings) == 1 else None,
            "spot": spot_payload,
            "legs_with_data": sum(1 for rows in leg_bars if rows),
            "errors": [f"{leg.label}: {leg.error}" for leg in combo_legs if leg.error],
            "settings": {"ema1": ema1, "ema2": ema2, "st_factor": st_factor, "st_atr": st_atr},
            "mode": cfg.mode,
            **payload,
        }

    # ---------------------------------------------------------- pages / assets
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    else:  # pragma: no cover - only if the vendored asset is missing
        log.warning("static assets missing at %s; charts will not render", static_dir)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard():
        return HTMLResponse(DASHBOARD_HTML)

    @app.get("/charts", response_class=HTMLResponse, include_in_schema=False)
    async def charts():
        return HTMLResponse(CHARTS_HTML)

    @app.get("/chain", response_class=HTMLResponse, include_in_schema=False)
    async def chain_page():
        return HTMLResponse(CHAIN_HTML)

    @app.get("/combo", response_class=HTMLResponse, include_in_schema=False)
    async def combo_page():
        return HTMLResponse(COMBO_HTML)

    return app
