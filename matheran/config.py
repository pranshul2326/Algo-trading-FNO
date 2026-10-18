"""Configuration loading. Secrets come from the environment, never from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787


@dataclass(slots=True)
class EngineConfig:
    poll_seconds: int = 15
    approval_ttl_seconds: int = 300
    cooldown_seconds: int = 120
    max_trades_per_day: int = 4
    max_open_positions: int = 3
    square_off_time: str = "15:15"      # INTRADAY positions only
    no_new_entry_after: str = "15:00"   # INTRADAY entries only
    market_open: str = "09:15"
    market_close: str = "15:30"
    # Product for new watches and orders unless one is chosen: INTRADAY is squared off
    # at square_off_time, DELIVERY (CNC / NRML) is carried until its exits fire.
    default_product: str = "INTRADAY"


@dataclass(slots=True)
class StrategyConfig:
    timeframe_minutes: int = 5           # entry: the candles the entry conditions read
    rsi_period: int = 21
    rsi_signal_entry_period: int = 21
    rsi_signal_exit_period: int = 9
    supertrend_period: int = 21
    supertrend_factor: float = 0.618
    price_ema_period: int = 21
    adx_period: int = 14
    adx_min: float | None = 20.0
    require_adx: bool = False
    entry_condition_mode: str = "state"  # state | cross
    entry_candle_type: str = "normal"    # normal | heikin_ashi
    exit_condition_mode: str = "state"

    # Which indicator exits are armed. Turning both off leaves only the stop, the
    # target and the end-of-day square-off. Only read while exit_rules is null.
    exit_on_rsi: bool = True
    exit_on_supertrend: bool = True

    # Exit conditions as rows - indicator, comparison, indicator or number - joined
    # by AND / OR, each checked on candle close or on the live price (rules.py).
    # null builds the rows from the three legacy settings above, which is all an
    # older config.yaml has. [] means no indicator exits at all.
    exit_rules: list | None = None
    # The candles the exit conditions read. null = each watch's own (entry)
    # timeframe, as before. Orders placed from a chart keep the chart's timeframe.
    exit_timeframe_minutes: int | None = None

    def warmup_bars(self) -> int:
        """Minimum closed candles needed before any signal can be trusted.

        Includes what the exit rules need, so a position is never opened whose exit
        conditions cannot be evaluated yet.
        """
        from .rules import effective_rules, rules_warmup

        rsi_chain = self.rsi_period + max(
            self.rsi_signal_entry_period, self.rsi_signal_exit_period
        )
        adx_chain = self.adx_period * 2
        base = max(rsi_chain, self.supertrend_period, self.price_ema_period, adx_chain) + 2
        return max(base, rules_warmup(effective_rules(self)) + 1)


@dataclass(slots=True)
class RiskConfig:
    stop_loss_pct: float = 3.0
    target_pct: float | None = None
    place_stop_at_broker: bool = True
    # Once price is this far in profit, pull the stop up to the entry price so the
    # trade cannot turn into a loss. null disables it.
    breakeven_trigger_pct: float | None = None
    # Allow a manual Buy that skips the signal. The approval gate is replaced by the
    # confirmation in the UI; every other guard (caps, halt, market hours) still applies.
    allow_manual_buy: bool = True
    # What closes a position unless a watch or an order says otherwise:
    #   both      - stop / target / trailing, and the Strategy tab's exit conditions
    #   sl_target - stop / target / trailing only
    #   strategy  - the exit conditions only (no stop at all, so use with care)
    exit_mode: str = "both"
    # Trailing profit: once a trade is trail_profit_trigger_pct in profit, the stop
    # follows the best price at trail_profit_value (% of that price, or points) and
    # never moves back. null disables it. Orders with their own trailing stop keep it.
    trail_profit_trigger_pct: float | None = None
    trail_profit_value: float | None = None
    trail_profit_unit: str = "pct"   # pct | pts


@dataclass(slots=True)
class OptionsConfig:
    otm_count: int = 5
    default_underlying: str = "NIFTY"
    expiry: str = "nearest"


@dataclass(slots=True)
class ScannerConfig:
    """The live BUY/SELL scanner (scanner.py). Rows are exit-rule rows plus `tf`."""

    buy_rules: list | None = None          # null = the seven default rows (scanner.DEFAULT_BUY_ROWS)
    sell_rules: list | None = None         # null = mirror of buy_rules ("linked")
    universes: list = field(default_factory=lambda: ["nifty50"])
    custom_symbols: list = field(default_factory=list)    # "NSE:RELIANCE", "BSE:TCS", "MCX:GOLD"
    side: str = "both"                     # both | buy | sell
    evaluation: str = "auto"               # auto | complete | lazy
    auto_rescan_minutes: int = 0           # 0 = off; 2 5 10 15 30 60. Only the console select's
                                           # default: loading never arms it
    max_requests_per_30min: int = 1500     # the scanner's own share of Upstox's 2,000 / 30 min
    requests_per_second: float = 6.0
    concurrency: int = 6


@dataclass(slots=True)
class BrokerConfig:
    name: str = "dhan"
    # Optional separate market-data provider. "upstox" serves candles free and
    # without credentials, which pairs well with Dhan's free Trading APIs.
    # None or "" means the execution broker also supplies data.
    data_broker: str | None = None


@dataclass(slots=True)
class Secrets:
    api_key: str | None = None
    dhan_access_token: str | None = None
    dhan_client_id: str | None = None
    stoxkart_api_key: str | None = None
    stoxkart_api_secret: str | None = None
    stoxkart_client_id: str | None = None
    stoxkart_password: str | None = None
    # Optional: Upstox candles need no auth, a token only upgrades LTP to live quotes.
    upstox_access_token: str | None = None

    @classmethod
    def from_env(cls) -> "Secrets":
        return cls(
            api_key=os.environ.get("MATHERAN_API_KEY") or None,
            dhan_access_token=os.environ.get("DHAN_ACCESS_TOKEN") or None,
            dhan_client_id=os.environ.get("DHAN_CLIENT_ID") or None,
            stoxkart_api_key=os.environ.get("STOXKART_API_KEY") or None,
            stoxkart_api_secret=os.environ.get("STOXKART_API_SECRET") or None,
            stoxkart_client_id=os.environ.get("STOXKART_CLIENT_ID") or None,
            stoxkart_password=os.environ.get("STOXKART_PASSWORD") or None,
            upstox_access_token=os.environ.get("UPSTOX_ACCESS_TOKEN") or None,
        )


@dataclass(slots=True)
class Config:
    mode: str = "paper"  # paper | live
    server: ServerConfig = field(default_factory=ServerConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    options: OptionsConfig = field(default_factory=OptionsConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    # Read from the environment even when a Config is built directly, otherwise a
    # programmatically created app would silently come up with no API key set.
    secrets: Secrets = field(default_factory=Secrets.from_env)
    data_dir: Path = field(default_factory=lambda: Path("data"))
    cache_dir: Path = field(default_factory=lambda: Path("cache"))
    # Workspace id -> workspaces.WorkspaceSettings (strategy, risk, setup defaults).
    # Built from deep copies of the sections above unless config.yaml saved its own
    # under `workspaces:`. Filled on load, or on first use for a Config built in code.
    workspaces: dict = field(default_factory=dict)

    @property
    def live(self) -> bool:
        return self.mode.lower() == "live"

    def workspace(self, workspace: str):
        """The settings of one workspace (see workspaces.py)."""
        from . import workspaces as ws_mod

        if workspace not in ws_mod.WORKSPACES:
            raise ValueError(f"unknown workspace {workspace!r}")
        if workspace not in self.workspaces:
            self.workspaces[workspace] = ws_mod.fresh(self, workspace)
        return self.workspaces[workspace]

    def strategy_for(self, workspace: str | None) -> StrategyConfig:
        """Strategy settings for a workspace; the top-level ones for anything else (a
        legacy record no workspace owns, or a caller that names none)."""
        from . import workspaces as ws_mod

        if workspace in ws_mod.WORKSPACES:
            return self.workspace(workspace).strategy
        return self.strategy

    def risk_for(self, workspace: str | None) -> RiskConfig:
        from . import workspaces as ws_mod

        if workspace in ws_mod.WORKSPACES:
            return self.workspace(workspace).risk
        return self.risk

    def defaults_for(self, workspace: str | None) -> dict:
        from . import workspaces as ws_mod

        if workspace in ws_mod.WORKSPACES:
            return self.workspace(workspace).defaults
        return {}


def _section(raw: dict[str, Any], key: str, cls):
    data = raw.get(key) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config section '{key}' must be a mapping")
    known = {f for f in cls.__dataclass_fields__}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown keys in config section '{key}': {sorted(unknown)}")
    return cls(**data)


def load_config(path: str | Path | None = None, *, load_env: bool = True) -> Config:
    """Load config.yaml if present, overlay environment secrets.

    `.env` is loaded here rather than left to the caller, so every entry point
    (CLI, uvicorn, a notebook) sees the same credentials. Real environment
    variables win over the file.
    """
    if load_env:
        try:
            from dotenv import load_dotenv

            load_dotenv(override=False)
        except ImportError:  # pragma: no cover - dotenv is a declared dependency
            pass

    raw: dict[str, Any] = {}
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"config file not found: {p}")
        raw = yaml.safe_load(p.read_text()) or {}
    else:
        for candidate in (Path("config.yaml"), Path("config.yml")):
            if candidate.exists():
                raw = yaml.safe_load(candidate.read_text()) or {}
                break

    cfg = Config(
        mode=str(raw.get("mode", "paper")),
        server=_section(raw, "server", ServerConfig),
        broker=_section(raw, "broker", BrokerConfig),
        engine=_section(raw, "engine", EngineConfig),
        strategy=_section(raw, "strategy", StrategyConfig),
        risk=_section(raw, "risk", RiskConfig),
        options=_section(raw, "options", OptionsConfig),
        scanner=_section(raw, "scanner", ScannerConfig),
        secrets=Secrets.from_env(),
    )
    # The top-level sections are validated (and normalised in place) first, so every
    # workspace copies settled values; then each workspace is built and validated.
    validate(cfg)
    from . import workspaces as ws_mod

    saved = raw.get("workspaces") or {}
    if not isinstance(saved, dict):
        raise ValueError("config section 'workspaces' must be a mapping")
    unknown = set(saved) - set(ws_mod.WORKSPACE_IDS)
    if unknown:
        raise ValueError(f"unknown workspaces in config: {sorted(unknown)}")
    for ws in ws_mod.WORKSPACE_IDS:
        cfg.workspaces[ws] = ws_mod.fresh(cfg, ws, saved.get(ws))
    validate(cfg)
    return cfg


def validate_trading(strategy: StrategyConfig, risk: RiskConfig, prefix: str = "") -> None:
    """Validate (and normalise in place) one strategy + risk pair: the top-level
    sections with no prefix, or a workspace's with prefix "workspaces.<id>."."""
    from .timeframes import MINUTES, code_of

    try:
        strategy.timeframe_minutes = int(strategy.timeframe_minutes)
    except (TypeError, ValueError):
        raise ValueError(f"{prefix}strategy.timeframe_minutes must be a number of minutes") from None
    if strategy.timeframe_minutes not in MINUTES:
        raise ValueError(
            f"{prefix}strategy.timeframe_minutes must be one of "
            + ", ".join(f"{m} ({code_of(m)})" for m in MINUTES)
        )
    exit_tf = strategy.exit_timeframe_minutes
    if exit_tf in ("", 0):
        exit_tf = None
    if exit_tf is not None:
        try:
            exit_tf = int(exit_tf)
        except (TypeError, ValueError):
            raise ValueError(
                f"{prefix}strategy.exit_timeframe_minutes must be a number of minutes or null"
            ) from None
        if exit_tf not in MINUTES:
            raise ValueError(
                f"{prefix}strategy.exit_timeframe_minutes must be null (same as entry) or one of "
                + ", ".join(f"{m} ({code_of(m)})" for m in MINUTES)
            )
    strategy.exit_timeframe_minutes = exit_tf
    if strategy.entry_condition_mode not in {"state", "cross"}:
        raise ValueError(f"{prefix}strategy.entry_condition_mode must be 'state' or 'cross'")
    from .candles import normalize_candle_type

    strategy.entry_candle_type = normalize_candle_type(
        strategy.entry_candle_type, f"{prefix}strategy.entry_candle_type"
    )
    if strategy.exit_condition_mode not in {"state", "cross"}:
        raise ValueError(f"{prefix}strategy.exit_condition_mode must be 'state' or 'cross'")
    from .rules import normalize_rules

    # Normalised in place: numbers typed into the console arrive as strings, and
    # missing parameters are filled with their defaults before anything reads them.
    strategy.exit_rules = normalize_rules(strategy.exit_rules)
    from .rules import effective_rules

    if str(risk.exit_mode).lower() == "strategy" and not effective_rules(strategy):
        raise ValueError(
            "exit mode 'exit conditions only' needs at least one exit condition; with "
            "none, nothing but the square-off or a manual exit would ever close a trade"
        )
    if not 0 < risk.stop_loss_pct < 100:
        raise ValueError(f"{prefix}risk.stop_loss_pct must be between 0 and 100")
    if risk.target_pct is not None and risk.target_pct <= 0:
        raise ValueError(f"{prefix}risk.target_pct must be positive or null")
    if risk.breakeven_trigger_pct is not None and risk.breakeven_trigger_pct <= 0:
        raise ValueError(f"{prefix}risk.breakeven_trigger_pct must be positive or null")
    if (
        risk.target_pct is not None
        and risk.breakeven_trigger_pct is not None
        and risk.breakeven_trigger_pct >= risk.target_pct
    ):
        raise ValueError(
            f"{prefix}risk.breakeven_trigger_pct must be below {prefix}risk.target_pct, "
            "otherwise the target fires first and the breakeven stop never moves"
        )
    mode = str(risk.exit_mode or "").lower()
    if mode not in {"both", "sl_target", "strategy"}:
        raise ValueError(f"{prefix}risk.exit_mode must be both, sl_target or strategy")
    risk.exit_mode = mode
    r = risk
    if r.trail_profit_unit not in {"pct", "pts"}:
        raise ValueError(f"{prefix}risk.trail_profit_unit must be pct or pts")
    trail_set = r.trail_profit_trigger_pct is not None or r.trail_profit_value is not None
    if trail_set:
        if r.trail_profit_trigger_pct is None or r.trail_profit_value is None:
            raise ValueError(
                f"trailing profit needs both {prefix}risk.trail_profit_trigger_pct and "
                f"{prefix}risk.trail_profit_value, or neither"
            )
        if r.trail_profit_trigger_pct <= 0 or r.trail_profit_value <= 0:
            raise ValueError("trailing profit trigger and distance must be positive")
        if r.trail_profit_unit == "pct" and r.trail_profit_value >= 100:
            raise ValueError("a trailing profit distance of 100% or more is not a usable stop")


def validate(cfg: Config) -> None:
    if cfg.mode.lower() not in {"paper", "live"}:
        raise ValueError("mode must be 'paper' or 'live'")
    validate_trading(cfg.strategy, cfg.risk)
    product = str(cfg.engine.default_product or "").upper()
    if product not in {"INTRADAY", "DELIVERY"}:
        raise ValueError("engine.default_product must be INTRADAY or DELIVERY")
    cfg.engine.default_product = product
    for ws, settings in cfg.workspaces.items():
        validate_trading(settings.strategy, settings.risk, prefix=f"workspaces.{ws}.")
    if cfg.broker.name not in {"dhan", "stoxkart", "paper"}:
        raise ValueError("broker.name must be one of dhan, stoxkart, paper")
    if cfg.broker.data_broker not in {None, "", "upstox", "dhan", "synthetic"}:
        raise ValueError("broker.data_broker must be upstox, dhan, synthetic or empty")
    if cfg.options.otm_count < 0 or cfg.options.otm_count > 20:
        raise ValueError("options.otm_count must be between 0 and 20")
    from .scanner import validate_config

    validate_config(cfg.scanner)


def with_overrides(cfg: Config, **overrides) -> Config:
    return replace(cfg, **overrides)
