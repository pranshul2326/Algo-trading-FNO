"""Basket orders: a named combination of legs executed together.

A basket is deliberately not a new execution path. Each leg becomes an ordinary
Watch with its own direction, so every protection already built and verified - the
3% stop, the indicator exits, the end-of-day square-off, the position caps - applies
to each leg without being reimplemented. The basket is the grouping plus a combined
price series.

Combined value convention, in premium points: a bought leg contributes +w x price, a
sold leg -w x price, where w is the leg's lots reduced by their common divisor (see
unit_weights). Legs in equal lots therefore chart as the plain sum or difference of
their prices, not as rupees. The line rising is always good news regardless of the
legs' directions.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

from .data_source import Bar
from .models import Direction, Instrument, new_id
from .timeutil import now_ist

log = logging.getLogger(__name__)


def _workspace(value) -> str:
    from .workspaces import WORKSPACES

    text = str(value or "").strip()
    return text if text in WORKSPACES else ""


@dataclass(slots=True)
class BasketLeg:
    symbol: str                   # chart symbol id, e.g. opt:NIFTY:2026-10-06:22700:CE
    direction: Direction          # LONG = buy this leg, SHORT = sell it
    quantity: int
    label: str = ""
    watch_id: str | None = None   # set once the leg has been armed

    @property
    def sign(self) -> int:
        return self.direction.sign

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "side": self.direction.entry_side.value,
            "quantity": self.quantity,
            "label": self.label,
            "watch_id": self.watch_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BasketLeg":
        return cls(
            symbol=str(data["symbol"]),
            direction=Direction(str(data.get("direction", "LONG")).upper()),
            quantity=int(data["quantity"]),
            label=str(data.get("label", "")),
            watch_id=data.get("watch_id"),
        )


@dataclass(slots=True)
class Basket:
    id: str
    name: str
    legs: list[BasketLeg]
    timeframe_minutes: int = 5
    stop_loss_pct: float | None = None
    target_pct: float | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=now_ist)
    state: str = "draft"  # draft | armed | executed | closed
    product: str = "INTRADAY"   # INTRADAY | DELIVERY, for every leg
    exit_mode: str = ""         # both | sl_target | strategy; "" = the Strategy tab's
    # The owning workspace (workspaces.py). "" on a basket from before workspaces,
    # which the legacy rule gives to Option Seller; its leg watches inherit it.
    workspace: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "legs": [l.as_dict() for l in self.legs],
            "timeframe_minutes": self.timeframe_minutes,
            "stop_loss_pct": self.stop_loss_pct,
            "target_pct": self.target_pct,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "state": self.state,
            "product": self.product,
            "exit_mode": self.exit_mode,
            "chart_symbol": f"basket:{self.id}",
            "net_quantity": sum(l.sign * l.quantity for l in self.legs),
            "leg_count": len(self.legs),
            "workspace": self.workspace,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Basket":
        created = data.get("created_at")
        try:
            ts = datetime.fromisoformat(str(created)) if created else now_ist()
        except ValueError:
            ts = now_ist()
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "basket")),
            legs=[BasketLeg.from_dict(l) for l in data.get("legs", [])],
            timeframe_minutes=int(data.get("timeframe_minutes", 5)),
            stop_loss_pct=data.get("stop_loss_pct"),
            target_pct=data.get("target_pct"),
            notes=str(data.get("notes", "")),
            created_at=ts,
            state=str(data.get("state", "draft")),
            product=str(data.get("product") or "INTRADAY").upper(),
            exit_mode=str(data.get("exit_mode") or "").lower(),
            workspace=_workspace(data.get("workspace")),
        )


def unit_weights(lots: list[float]) -> list[float]:
    """Leg weights for a combined premium chart, in points rather than rupees.

    Lots are divided by their greatest common divisor, so legs in equal lots plot as
    the plain sum or difference of their prices whatever the lot count, while a 1:2
    ratio spread still plots A - 2B. Fractional lots are left as they are.
    """
    if not lots:
        return []
    whole = [round(x) for x in lots]
    if any(abs(x - w) > 1e-9 or w <= 0 for x, w in zip(lots, whole)):
        return list(lots)
    g = 0
    for w in whole:
        g = math.gcd(g, int(w))
    return [w / g for w in whole] if g > 1 else [float(w) for w in whole]


def leg_profile(symbol: str) -> tuple[str, bool]:
    """(underlying, rises_with_it) read from a chart symbol id.

    A call, a future and the stock itself rise with the underlying; a put falls.
    """
    kind, _, rest = symbol.partition(":")
    if kind == "opt":
        parts = rest.split(":")
        if len(parts) == 4:
            return parts[0].upper(), parts[3].upper() != "PE"
    if kind == "fut":
        return rest.split(":")[0].upper(), True
    if kind == "eq":
        return rest.split(":")[-1].upper(), True
    return rest.upper() or symbol.upper(), True


def combine(
    leg_bars: list[tuple[float, list[Bar]]], rises: list[bool] | None = None
) -> list[Bar]:
    """Merge per-leg bars into one series for the basket.

    `leg_bars` is (signed weight, bars) per leg. Only timestamps present in every
    leg are used, because a basket value computed from a missing leg is a lie.
    Open and close are exact: the signed sum of the legs' opens and closes.

    High and low cannot be summed, because the legs did not all peak at the same
    instant. Two readings:

    * `rises` given (every leg on one underlying, True where the leg rises with
      it): the whole combination is valued at the moment the underlying made its
      high - calls, futures and stock at their highs, puts at their lows - and again
      at its low, the reverse. That is a range the basket could actually have
      traded, the same pairing as the TradingView combo script.
    * otherwise (legs on different underlyings): each leg at its own best case, a
      short leg contributing its low to the high. This is the widest possible
      bound, since nothing ties the legs' extremes together.

    Either way the bar is widened to contain its own open and close, so it is
    always a valid candle.
    """
    if not leg_bars:
        return []

    indexed = [({b.time: b for b in bars}, qty) for qty, bars in leg_bars if bars]
    if len(indexed) != len(leg_bars):
        return []  # a leg had no data at all
    linked = rises is not None and len(rises) == len(indexed)

    common = set(indexed[0][0])
    for book, _qty in indexed[1:]:
        common &= set(book)
    if not common:
        return []

    out: list[Bar] = []
    for t in sorted(common):
        o = c = 0.0
        a = b = 0.0  # linked: value at the underlying's high / low; else widest high / low
        vol = 0.0
        oi = 0.0
        for k, (book, qty) in enumerate(indexed):
            bar = book[t]
            o += qty * bar.open
            c += qty * bar.close
            if linked:
                up = rises[k]
                a += qty * (bar.high if up else bar.low)
                b += qty * (bar.low if up else bar.high)
            elif qty >= 0:
                a += qty * bar.high
                b += qty * bar.low
            else:
                a += qty * bar.low
                b += qty * bar.high
            vol += bar.volume
            oi += bar.oi
        h = max(a, b, o, c)
        l = min(a, b, o, c)
        out.append(
            Bar(time=t, open=round(o, 4), high=round(h, 4), low=round(l, 4),
                close=round(c, 4), volume=vol, oi=oi)
        )
    return out


class BasketStore:
    """Baskets held in memory and mirrored to disk by the caller's Store."""

    def __init__(self) -> None:
        self.baskets: dict[str, Basket] = {}

    def create(
        self,
        *,
        name: str,
        legs: list[BasketLeg],
        timeframe_minutes: int = 5,
        stop_loss_pct: float | None = None,
        target_pct: float | None = None,
        notes: str = "",
        product: str = "INTRADAY",
        exit_mode: str = "",
        workspace: str = "",
    ) -> Basket:
        if not legs:
            raise ValueError("a basket needs at least one leg")
        if len(legs) > 10:
            raise ValueError("a basket is limited to 10 legs")
        seen: set[tuple[str, str]] = set()
        for leg in legs:
            if leg.quantity <= 0:
                raise ValueError(f"leg {leg.symbol} needs a positive quantity")
            key = (leg.symbol, leg.direction.value)
            if key in seen:
                raise ValueError(f"duplicate leg {leg.symbol} {leg.direction.value}")
            seen.add(key)
        # Buying and selling the same contract in one basket nets to nothing but
        # still pays two lots of brokerage, so it is refused as a mistake.
        for leg in legs:
            opposite = (leg.symbol, Direction.SHORT.value
                        if leg.direction is Direction.LONG else Direction.LONG.value)
            if opposite in seen:
                raise ValueError(
                    f"{leg.symbol} appears both bought and sold; that nets to zero"
                )

        basket = Basket(
            id=new_id("bk"),
            name=name.strip() or "basket",
            legs=legs,
            timeframe_minutes=timeframe_minutes,
            stop_loss_pct=stop_loss_pct,
            target_pct=target_pct,
            notes=notes,
            product=product,
            exit_mode=exit_mode,
            workspace=workspace,
        )
        self.baskets[basket.id] = basket
        log.info("baskets: created %s '%s' with %d legs", basket.id, basket.name, len(legs))
        return basket

    def get(self, basket_id: str) -> Basket:
        basket = self.baskets.get(basket_id)
        if basket is None:
            raise ValueError(f"no such basket: {basket_id}")
        return basket

    def remove(self, basket_id: str) -> None:
        self.baskets.pop(basket_id, None)

    def all(self) -> list[Basket]:
        return sorted(self.baskets.values(), key=lambda b: b.created_at, reverse=True)

    def to_list(self) -> list[dict]:
        return [b.as_dict() for b in self.all()]

    def load(self, rows: list[dict]) -> None:
        for row in rows:
            try:
                basket = Basket.from_dict(row)
                self.baskets[basket.id] = basket
            except (KeyError, TypeError, ValueError) as exc:
                log.error("baskets: skipping malformed record: %s", exc)
