"""Saidarshan's three trading workspaces: identity, navigation, ownership, settings.

A workspace scopes what a person sees and edits - the child views, the setup
defaults, the strategy and risk settings, the watches, orders, baskets and journal
rows it owns. It does not scope the machinery: there is one engine, one broker, one
indicator library and one set of safety controls (mode, credentials, halt, the
position and per-day caps, market hours), shared by all three.

Ownership of a record is explicit for everything created from now on: watches,
trades, approvals and baskets carry a `workspace`. Records written before workspaces
existed carry none, and are assigned by one deterministic rule that reads only the
record itself, so an old record lands in exactly one journal and never moves:

  * a basket, or a watch that is a basket leg       -> Option Seller
  * an NSE/BSE cash equity                           -> Stock Intraday
  * an option bought (LONG)                          -> Option Buyer
  * an option sold (SHORT)                           -> Option Seller
  * anything else (futures, a two-way option watch)  -> legacy, shown on the
                                                        System page only
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any

STOCK_INTRADAY = "stock_intraday"
OPTION_BUYER = "option_buyer"
OPTION_SELLER = "option_seller"
WORKSPACE_IDS: tuple[str, ...] = (STOCK_INTRADAY, OPTION_BUYER, OPTION_SELLER)
LEGACY = "legacy"
"""An old record the rule above cannot honestly assign to one workspace."""

CASH_SEGMENTS = {"NSE_EQ", "BSE_EQ"}

# Child views in their exact display order. `page` marks the views that are their own
# document (the charts, option chain and combo screens), served inside the app shell.
WORKSPACES: dict[str, dict] = {
    STOCK_INTRADAY: {
        "id": STOCK_INTRADAY,
        "slug": "stock-intraday",
        "label": "Stock Intraday",
        "views": (
            ("setup", "Setup"),
            ("scanner", "Scanner"),
            ("strategy", "Strategy"),
            ("trade", "Trade"),
            ("journal", "Journal"),
            ("chart", "Chart"),
        ),
    },
    OPTION_BUYER: {
        "id": OPTION_BUYER,
        "slug": "option-buyer",
        "label": "Option Buyer",
        "views": (
            ("setup", "Setup"),
            ("option-scan", "Option Scan"),
            ("strategy", "Strategy"),
            ("trade", "Trade"),
            ("journal", "Journal"),
            ("chart", "Chart"),
        ),
    },
    OPTION_SELLER: {
        "id": OPTION_SELLER,
        "slug": "option-seller",
        "label": "Option Seller",
        "views": (
            ("setup", "Setup"),
            ("straddle-scan", "Straddle Scan"),
            ("option-chain", "Option Chain"),
            ("basket", "Basket"),
            ("strategy", "Strategy"),
            ("chart", "Chart"),
            ("combo-chart", "Combo Chart"),
            ("journal", "Journal"),
        ),
    },
}
PAGE_VIEWS = {"chart": "charts", "option-chain": "chain", "combo-chart": "combo"}
BY_SLUG = {w["slug"]: w["id"] for w in WORKSPACES.values()}

# Old dashboard bookmarks (/#trade and friends): where each one lives now. The old
# Setup tab held the connection, mode and credentials, which apply to all workspaces
# and so live on the System page (workspace None).
LEGACY_HASHES: dict[str, tuple[str | None, str]] = {
    "setup": (None, "system"),
    "trade": (STOCK_INTRADAY, "trade"),
    "scanner": (STOCK_INTRADAY, "scanner"),
    "strategy": (STOCK_INTRADAY, "strategy"),
    "journal": (STOCK_INTRADAY, "journal"),
    "options": (OPTION_BUYER, "option-scan"),
    "baskets": (OPTION_SELLER, "basket"),
}


def legacy_hash_paths() -> dict[str, str]:
    """Each old bookmark hash and the /app path it opens now."""
    return {
        key: f"/app/{WORKSPACES[ws]['slug']}/{view}" if ws else f"/app/{view}"
        for key, (ws, view) in LEGACY_HASHES.items()
    }


def label_of(workspace: str | None) -> str:
    if workspace in WORKSPACES:
        return WORKSPACES[workspace]["label"]
    return "Unclassified (legacy)"


def normalize(value: Any, *, allow_legacy: bool = False) -> str | None:
    """A workspace id from an id, a URL slug or a label; None when empty.

    Raises ValueError for anything else, so a typo never silently lands a record in
    the wrong workspace.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower().replace(" ", "_")
    if key in WORKSPACES:
        return key
    if text.lower() in BY_SLUG:
        return BY_SLUG[text.lower()]
    if allow_legacy and key in {LEGACY, "unclassified"}:
        return LEGACY
    allowed = ", ".join(WORKSPACE_IDS) + (f", {LEGACY}" if allow_legacy else "")
    raise ValueError(f"workspace must be one of {allowed}, got {text!r}")


def view_ids(workspace: str) -> list[str]:
    return [view for view, _label in WORKSPACES[workspace]["views"]]


def navigation() -> list[dict]:
    """The two navigation levels, in display order, for the app shell."""
    return [
        {
            "id": w["id"],
            "slug": w["slug"],
            "label": w["label"],
            "views": [
                {"id": view, "label": text, "page": PAGE_VIEWS.get(view),
                 "href": f"/app/{w['slug']}/{view}"}
                for view, text in w["views"]
            ],
        }
        for w in WORKSPACES.values()
    ]


# ------------------------------------------------------------------ ownership
def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_option(instrument: Any) -> bool:
    option_type = str(_get(instrument, "option_type") or "").upper()
    kind = str(_get(instrument, "instrument_type") or "").upper()
    return option_type in {"CE", "PE"} or kind.startswith("OPT")


def assign(instrument: Any, sides: str | None, basket_id: str | None = None) -> str:
    """The workspace the legacy rule gives a record (see the module docstring)."""
    if basket_id:
        return OPTION_SELLER
    if str(_get(instrument, "segment") or "").upper() in CASH_SEGMENTS:
        return STOCK_INTRADAY
    if _is_option(instrument):
        side = str(sides or "").upper()
        if side == "LONG":
            return OPTION_BUYER
        if side == "SHORT":
            return OPTION_SELLER
    return LEGACY


def of_watch(watch: Any) -> str:
    """A watch's workspace: its own, else the legacy rule on its instrument and sides."""
    explicit = str(_get(watch, "workspace") or "")
    if explicit in WORKSPACES:
        return explicit
    sides = _get(watch, "sides") or _get(watch, "direction")
    sides = getattr(sides, "value", sides)
    return assign(_get(watch, "instrument") or {}, sides, _get(watch, "basket_id"))


def of_trade(row: dict) -> str:
    """A journal row's workspace: its own (a workspace, or "legacy" when it closed on a
    watch no workspace owns), else the legacy rule on the row alone."""
    explicit = str(row.get("workspace") or "")
    if explicit in WORKSPACES or explicit == LEGACY:
        return explicit
    return assign(row.get("instrument") or {}, row.get("direction"), row.get("basket_id"))


def of_basket(basket: Any) -> str:
    explicit = str(_get(basket, "workspace") or "")
    return explicit if explicit in WORKSPACES else OPTION_SELLER


def for_new(workspace: Any, instrument: Any, sides: str | None,
            basket_id: str | None = None) -> str:
    """The owner of a record being created now, as stored on it.

    An explicit workspace wins; the console always sends one. A caller that sends none
    (an API client from before workspaces) gets the legacy rule, the documented
    compatibility default. A record the rule cannot place (a future, a two-way option
    watch) is stored with "" and listed under System > Unclassified, never in two
    journals.
    """
    chosen = normalize(workspace)
    if chosen:
        return chosen
    assigned = assign(instrument, sides, basket_id)
    return "" if assigned == LEGACY else assigned


def assigned_by(record: Any) -> str:
    """'record' when the record names its workspace, 'legacy rule' when it was assigned."""
    return "record" if str(_get(record, "workspace") or "") in WORKSPACES else "legacy rule"


# ------------------------------------------------------------- setup defaults
_PRODUCTS = ("INTRADAY", "DELIVERY")
_EXIT_MODES = ("", "both", "sl_target", "strategy")
_CANDLES = ("normal", "heikin_ashi")
_TIMEFRAMES = (1, 3, 5, 9, 15, 30, 60, 120, 1440, 10080, 43200)


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label: str
    kind: str                     # choice | int | float | text
    default: Any
    choices: tuple = ()
    lo: float | None = None
    hi: float | None = None
    optional: bool = False        # blank allowed (None), e.g. "no target"
    help: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "default": self.default, "choices": list(self.choices), "min": self.lo,
                "max": self.hi, "optional": self.optional, "help": self.help}


def _schema(engine_product: str, underlying: str, otm: int, adx_min: float | None):
    product = engine_product if engine_product in _PRODUCTS else "INTRADAY"
    exit_help = "blank = the Strategy tab's exit mode"
    return {
        STOCK_INTRADAY: (
            Field("exchange", "Exchange", "choice", "NSE", ("NSE", "BSE")),
            Field("quantity", "Quantity (shares)", "int", 1, lo=1, hi=1_000_000),
            Field("direction", "Direction", "choice", "LONG", ("LONG", "SHORT", "BOTH")),
            Field("product", "Product", "choice", product, _PRODUCTS),
            Field("exit_mode", "Exit by", "choice", "", _EXIT_MODES, help=exit_help),
        ),
        OPTION_BUYER: (
            Field("underlying", "Underlying", "text", underlying),
            Field("otm_count", "OTM strikes each side", "int", otm, lo=0, hi=20),
            Field("timeframe_minutes", "Scan timeframe (minutes)", "choice", 1, _TIMEFRAMES),
            Field("candle_type", "Candle type", "choice", "normal", _CANDLES),
            Field("reference", "ATM from", "choice", "index", ("index", "future")),
            Field("adx_min", "ADX minimum", "float", 20.0 if adx_min is None else float(adx_min),
                  lo=0, hi=100),
            Field("lots", "Lots to buy", "int", 1, lo=1, hi=10_000),
            Field("product", "Product", "choice", product, _PRODUCTS),
            Field("exit_mode", "Exit by", "choice", "", _EXIT_MODES, help=exit_help),
        ),
        OPTION_SELLER: (
            Field("underlying", "Underlying", "text", underlying),
            Field("timeframe_minutes", "Straddle timeframe (minutes)", "choice", 1, _TIMEFRAMES),
            Field("candle_type", "Candle type", "choice", "normal", _CANDLES),
            Field("lots", "Lots per leg", "int", 1, lo=1, hi=10_000),
            Field("chain_strikes", "Option chain strikes each side", "choice", 8, (5, 8, 10, 15)),
            Field("chain_window", "Buildup window (minutes)", "choice", 5, (1, 3, 5, 15)),
            Field("product", "Product", "choice", product, _PRODUCTS),
            Field("exit_mode", "Exit by", "choice", "", _EXIT_MODES, help=exit_help),
            Field("stop_loss_pct", "Stop % per leg", "float", None, lo=0.1, hi=99,
                  optional=True, help="blank = the Strategy tab's stop"),
            Field("target_pct", "Target % per leg", "float", None, lo=0.1, hi=1000,
                  optional=True, help="blank = none"),
        ),
    }


def defaults_schema(cfg) -> dict[str, tuple[Field, ...]]:
    return _schema(str(cfg.engine.default_product).upper(),
                   str(cfg.options.default_underlying or "NIFTY").upper(),
                   int(cfg.options.otm_count), cfg.strategy.adx_min)


def check_defaults(workspace: str, values: dict, schema: dict[str, tuple[Field, ...]],
                   base: dict | None = None) -> dict:
    """Validated setup defaults: `base` (or the schema defaults) overlaid with `values`."""
    fields = {f.key: f for f in schema[workspace]}
    unknown = set(values or {}) - set(fields)
    if unknown:
        raise ValueError(f"{label_of(workspace)} setup: unknown settings {sorted(unknown)}")
    out = dict(base) if base else {f.key: f.default for f in fields.values()}
    for key, raw in (values or {}).items():
        f = fields[key]
        where = f"{label_of(workspace)} setup: {f.label.lower()}"
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if f.optional:
                out[key] = None
                continue
            if f.kind == "choice" and "" in f.choices:
                out[key] = ""
                continue
            raise ValueError(f"{where} is required")
        if f.kind == "text":
            text = str(raw).strip().upper()
            if not text.replace("-", "").replace("&", "").isalnum() or len(text) > 30:
                raise ValueError(f"{where} must be a symbol such as NIFTY")
            out[key] = text
            continue
        if f.kind == "choice":
            want = raw
            if all(isinstance(c, int) for c in f.choices if c != ""):
                try:
                    want = int(float(raw))
                except (TypeError, ValueError):
                    raise ValueError(f"{where} must be one of {list(f.choices)}") from None
            elif isinstance(raw, str):
                want = raw.strip()
                if f.key in {"exchange", "direction", "product"}:
                    want = want.upper()
                elif f.key in {"exit_mode", "candle_type", "reference"}:
                    want = want.lower()
            if want not in f.choices:
                raise ValueError(f"{where} must be one of {[c for c in f.choices if c != '']}")
            out[key] = want
            continue
        try:
            num = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{where} must be a number") from None
        if not math.isfinite(num) or (f.lo is not None and num < f.lo) or (
                f.hi is not None and num > f.hi):
            raise ValueError(f"{where} must be between {f.lo:g} and {f.hi:g}")
        if f.kind == "int":
            if not num.is_integer():
                raise ValueError(f"{where} must be a whole number")
            num = int(num)
        out[key] = num
    return out


# ---------------------------------------------------------- scoped settings
@dataclass(slots=True)
class WorkspaceSettings:
    """One workspace's strategy, risk and setup defaults.

    Each part either follows the top-level config.yaml section (the migration default,
    copied deeply so no two workspaces ever share a mutable object) or was saved for
    this workspace, in which case it is persisted under workspaces.<id>.<part>.
    """

    strategy: Any
    risk: Any
    defaults: dict
    customised: dict = field(default_factory=lambda: {"strategy": False, "risk": False,
                                                      "defaults": False})


def fresh(cfg, workspace: str, saved: dict | None = None) -> WorkspaceSettings:
    """A workspace built from deep copies of the top-level sections, overlaid with
    whatever was saved for it."""
    saved = saved or {}
    if not isinstance(saved, dict):
        raise ValueError(f"config section 'workspaces.{workspace}' must be a mapping")
    unknown = set(saved) - {"strategy", "risk", "defaults"}
    if unknown:
        raise ValueError(f"unknown keys in 'workspaces.{workspace}': {sorted(unknown)}")
    strategy = copy.deepcopy(cfg.strategy)
    risk = copy.deepcopy(cfg.risk)
    customised = {"strategy": False, "risk": False, "defaults": False}
    for part, obj in (("strategy", strategy), ("risk", risk)):
        values = saved.get(part)
        if values is None:
            continue
        if not isinstance(values, dict):
            raise ValueError(f"'workspaces.{workspace}.{part}' must be a mapping")
        for key, value in values.items():
            if key not in obj.__dataclass_fields__:
                raise ValueError(f"unknown {part} setting in workspaces.{workspace}: {key}")
            setattr(obj, key, copy.deepcopy(value))
        customised[part] = True
    schema = defaults_schema(cfg)
    defaults = check_defaults(workspace, {}, schema)
    if saved.get("defaults") is not None:
        if not isinstance(saved["defaults"], dict):
            raise ValueError(f"'workspaces.{workspace}.defaults' must be a mapping")
        defaults = check_defaults(workspace, saved["defaults"], schema)
        customised["defaults"] = True
    return WorkspaceSettings(strategy=strategy, risk=risk, defaults=defaults,
                             customised=customised)


def refresh_followers(cfg) -> None:
    """Re-copy the parts that follow the top-level sections after those changed (an
    older client saving strategy or risk without a workspace)."""
    for ws in WORKSPACE_IDS:
        current = cfg.workspaces.get(ws)
        if current is None:
            cfg.workspaces[ws] = fresh(cfg, ws)
            continue
        if not current.customised.get("strategy"):
            current.strategy = copy.deepcopy(cfg.strategy)
        if not current.customised.get("risk"):
            current.risk = copy.deepcopy(cfg.risk)
        if not current.customised.get("defaults"):
            current.defaults = check_defaults(ws, {}, defaults_schema(cfg))


def snapshot(cfg) -> dict:
    """The customised parts only, as persisted to config.yaml."""
    out: dict = {}
    for ws in WORKSPACE_IDS:
        current = cfg.workspaces.get(ws)
        if current is None:
            continue
        block = {}
        if current.customised.get("strategy"):
            block["strategy"] = {f: copy.deepcopy(getattr(current.strategy, f))
                                 for f in current.strategy.__dataclass_fields__}
        if current.customised.get("risk"):
            block["risk"] = {f: copy.deepcopy(getattr(current.risk, f))
                             for f in current.risk.__dataclass_fields__}
        if current.customised.get("defaults"):
            block["defaults"] = dict(current.defaults)
        if block:
            out[ws] = block
    return out
