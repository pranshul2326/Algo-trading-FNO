"""Pluggable chart data sources.

To add a broker, write one async function and register it. Nothing else in the
project needs to change - the charts page reads the registry and puts every
registered name in the source dropdown.

    from .data_source import Bar, SymbolRef, register

    @register("binance", label="Binance spot")
    class BinanceSource(DataSource):
        async def search(self, query, limit): ...
        async def candles(self, symbol, timeframe, bars): ...

Or, if you only need candles from a plain HTTP endpoint, subclass DataSource and
implement those two methods. `search` feeds the symbol picker, `candles` feeds the
chart. That is the whole contract.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable

from . import timeframes as tf_table
from .brokers.base import Broker, BrokerError
from .candles import CandleSeries
from .timeutil import now_ist

log = logging.getLogger(__name__)

# "NIFTY 25000", "NIFTY 25000 CE", "BANKNIFTY55000PE", "M&M 3000 PE": an underlying,
# a strike (or the start of one) and an optional side.
_CONTRACT_QUERY = re.compile(r"^([A-Z][A-Z&\-]*?)\s*(\d+(?:\.\d+)?)\s*(CE|PE)?$")

# Timeframes offered per pane, from the one table in timeframes.py: 1m 3m 5m 9m 15m
# 30m 1h 2h 1D 1W 1M. Intraday bars are resampled from 1-minute candles; earlier
# sessions and the day, week and month bars come from the provider's history.
TIMEFRAMES: tuple[tuple[str, int], ...] = tuple((c, m) for c, m, _ in tf_table.TIMEFRAMES)
TIMEFRAME_MINUTES = dict(TIMEFRAMES)
DEFAULT_BARS = 400


@dataclass(slots=True)
class Bar:
    """One OHLCV bar, in the shape Lightweight Charts wants."""

    time: int  # UNIX seconds, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    oi: float = 0.0  # open interest, derivatives only

    def as_dict(self) -> dict:
        return {
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "oi": self.oi,
        }


@dataclass(slots=True)
class SymbolRef:
    """One entry in a pane's symbol dropdown."""

    id: str                      # opaque, passed back to candles()
    label: str                   # what the dropdown shows
    group: str = ""              # optgroup heading, e.g. "Equity" / "NIFTY options"
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "group": self.group, **self.extra}


class DataSource(ABC):
    """Implement these two methods and the charts page works."""

    name: str = "base"
    label: str = "Base"

    @abstractmethod
    async def search(self, query: str, limit: int = 40) -> list[SymbolRef]:
        """Symbols matching `query`. An empty query should return sensible defaults."""

    @abstractmethod
    async def candles(self, symbol: str, timeframe: str, bars: int = DEFAULT_BARS) -> list[Bar]:
        """Most recent `bars` OHLCV bars for `symbol` at `timeframe`, oldest first.

        `timeframe` is one of the codes in timeframes.TIMEFRAMES (1m ... 1M); the API
        normalises older spellings such as 60m before calling this."""

    async def close(self) -> None:
        return None


# --------------------------------------------------------------------- registry
_REGISTRY: dict[str, Callable[..., DataSource]] = {}
_LABELS: dict[str, str] = {}


def register(name: str, *, label: str | None = None):
    """Class decorator that adds a source to the dropdown."""

    def wrap(cls):
        cls.name = name
        cls.label = label or name.title()
        _REGISTRY[name] = cls
        _LABELS[name] = cls.label
        return cls

    return wrap


def available() -> list[dict]:
    return [{"name": n, "label": _LABELS[n]} for n in sorted(_REGISTRY)]


def build(name: str, **kwargs) -> DataSource:
    if name not in _REGISTRY:
        raise BrokerError(
            f"unknown chart data source '{name}'. Registered: {sorted(_REGISTRY) or 'none'}"
        )
    return _REGISTRY[name](**kwargs)


# ------------------------------------------------------------ broker-backed source
def chart_symbol_for(instrument) -> str:
    """The chart symbol id for an engine instrument - the inverse of `_resolve`."""
    segment = instrument.segment or ""
    if instrument.instrument_type == "INDEX" or segment == "IDX_I":
        return f"idx:{instrument.symbol.upper()}"
    if segment == "MCX_COMM":
        und = (instrument.underlying or instrument.symbol).upper()
        return f"mcx:{und}" + (f":{instrument.expiry}" if instrument.expiry else "")
    if (
        instrument.option_type in ("CE", "PE")
        and instrument.underlying
        and instrument.expiry
        and instrument.strike is not None
    ):
        return (
            f"opt:{instrument.underlying.upper()}:{instrument.expiry}:"
            f"{instrument.strike:g}:{instrument.option_type}"
        )
    if (instrument.instrument_type or "").startswith("FUT") and instrument.underlying:
        return f"fut:{instrument.underlying.upper()}" + (
            f":{instrument.expiry}" if instrument.expiry else ""
        )
    exchange = "BSE" if segment.startswith("BSE") else "NSE"
    return f"eq:{exchange}:{instrument.symbol.upper()}"


def _to_bars(series: CandleSeries, limit: int) -> list[Bar]:
    out = [
        Bar(
            time=int(c.ts.timestamp()),
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
            oi=c.oi,
        )
        for c in series.candles
    ]
    return out[-limit:] if limit and len(out) > limit else out


@register("broker", label="Configured broker (Upstox / Dhan)")
class BrokerDataSource(DataSource):
    """Charts fed by whichever broker the engine is already using.

    This reuses the running broker, so the charts show exactly the candles the
    strategy is evaluating - no second opinion, no drift between what you see and
    what the engine acts on.
    """

    def __init__(self, broker: Broker | None = None, baskets=None, **_ignored):
        if broker is None:
            raise BrokerError("the broker data source needs a live broker instance")
        self.broker = broker
        # Optional basket registry: lets `basket:<id>` be charted like any symbol, so
        # indicators apply to a combination without any special-casing downstream.
        self.baskets = baskets

    INDEX_NAMES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")

    async def search(
        self,
        query: str,
        limit: int = 40,
        *,
        exchanges: tuple[str, ...] = ("NSE",),
        upstox=None,
    ) -> list[SymbolRef]:
        if tuple(exchanges) != ("NSE",):
            # The scanner's suggest: cash equities and MCX near months only.
            return await self._search_exchanges(query, limit, tuple(exchanges), upstox)
        raw = (query or "").strip()
        # A label pasted back ("RELIANCE — Reliance Industries") searches by its ticker.
        if " — " in raw:
            raw = raw.split(" — ", 1)[0]
        q = raw.upper()

        contracts: list[SymbolRef] = []
        baskets = self._basket_refs(q)
        indices: list[SymbolRef] = []
        futures_out: list[SymbolRef] = []
        equities_out: list[SymbolRef] = []
        options_out: list[SymbolRef] = []

        # An explicit contract - "NIFTY 25000", "BANKNIFTY 55000 PE", "RELIANCE1400CE" -
        # goes straight to the matching strikes of the nearest two expiries.
        wanted = _CONTRACT_QUERY.match(q)
        if wanted:
            contracts = await self._contract_refs(
                wanted.group(1), wanted.group(2), wanted.group(3)
            )

        # Index spots: the most-watched instruments, and they cost nothing.
        for name in self.INDEX_NAMES:
            if not q or q in name:
                indices.append(SymbolRef(id=f"idx:{name}", label=f"{name} (spot)", group="Index"))

        # Cash-segment names, straight from whichever instrument master is loaded.
        # Matching the company name as well means "vishal" finds VMM.
        await self._warm_instruments()
        equities = self._equity_index()
        if equities:
            hits = []
            for (exchange, symbol), inst in equities.items():
                if exchange != "NSE" or self._is_test(symbol):
                    continue
                if not q:
                    bucket = 0
                elif symbol == q:
                    bucket = 0
                elif symbol.startswith(q):
                    bucket = 1
                elif q in symbol:
                    bucket = 2
                elif len(q) >= 3 and q in (inst.display_name or "").upper():
                    bucket = 3
                else:
                    continue
                hits.append((bucket, self._liquidity_rank(symbol), symbol, inst))
            # Exact ticker, then prefix, then substring, then company name; inside each
            # group liquid names come first, so "SBI" offers SBIN before SBIBPB and an
            # empty box opens on RELIANCE rather than on exchange test scrips.
            hits.sort(key=lambda row: row[:3])
            for *_rank, inst in hits[:limit]:
                equities_out.append(
                    SymbolRef(
                        id=f"eq:NSE:{inst.symbol}",
                        label=f"{inst.symbol} — {inst.display_name[:34]}",
                        group="NSE equity",
                    )
                )

        # Futures for the index underlyings are always worth offering, since the
        # options strategy references the underlying future directly. A stock future
        # appears once its underlying is typed in full.
        futures = self._futures_index()
        for und in self.INDEX_NAMES:
            if (q and q not in und) or und not in futures:
                continue
            for fut in self._futures_for(und)[:2]:
                futures_out.append(
                    SymbolRef(id=f"fut:{und}:{fut.expiry}", label=f"{und} FUT {fut.expiry}",
                              group="Futures")
                )
        # A stock's future goes after the stock itself: typing a ticker means the
        # stock first.
        stock_futures: list[SymbolRef] = []
        if q and q not in self.INDEX_NAMES and q in futures:
            for fut in self._futures_for(q)[:1]:
                stock_futures.append(
                    SymbolRef(id=f"fut:{q}:{fut.expiry}", label=f"{q} FUT {fut.expiry}",
                              group="Futures")
                )

        # A typed underlying also gets its option strikes around the money, so an
        # option chart is reachable from the textbox and not only from the chain.
        if q and len(q) >= 3 and not wanted:
            options_out = await self._option_refs(q, span=4)

        if stock_futures and equities_out:
            # Right after the exact ticker, ahead of the looser name matches.
            head = 1 if equities_out[0].id == f"eq:NSE:{q}" else 0
            equities_out[head:head] = stock_futures
        else:
            equities_out.extend(stock_futures)
        out = contracts + baskets + indices + futures_out + equities_out + options_out
        return out[:limit]

    async def _search_exchanges(
        self, query: str, limit: int, exchanges: tuple[str, ...], upstox
    ) -> list[SymbolRef]:
        """Cash equities of the named exchanges and MCX near-month commodities, in the
        order MCX head (underlying = or starts with the text), NSE, BSE, MCX tail.
        Each exchange is capped at ceil(limit / len(exchanges)). Best-effort: a missing
        Upstox node or master leaves that group empty."""
        from .brokers import find_upstox

        raw = (query or "").strip()
        if " — " in raw:
            raw = raw.split(" — ", 1)[0]
        q = raw.upper()
        cap = max(1, math.ceil(limit / max(1, len(exchanges))))
        up = upstox if upstox is not None else find_upstox(self.broker)

        nse_out: list[SymbolRef] = []
        if "NSE" in exchanges:
            await self._warm_instruments()
            for inst in self._equity_hits(self._equity_index(), "NSE", q)[:cap]:
                nse_out.append(
                    SymbolRef(
                        id=f"eq:NSE:{inst.symbol}",
                        label=f"{inst.symbol} — {inst.display_name[:34]}",
                        group="NSE equity",
                    )
                )

        bse_out: list[SymbolRef] = []
        if "BSE" in exchanges and up is not None:
            try:
                holder = await up.exchange_instruments("BSE")
            except BrokerError as exc:
                log.warning("charts: could not load the BSE instruments: %s", exc)
                holder = None
            if holder is not None:
                for inst in self._equity_hits(holder.equities, "BSE", q)[:cap]:
                    bse_out.append(
                        SymbolRef(
                            id=f"eq:BSE:{inst.symbol}",
                            label=f"{inst.symbol} — {(inst.display_name or '')[:30]} (BSE)",
                            group="BSE equity",
                        )
                    )

        head: list[SymbolRef] = []
        tail: list[SymbolRef] = []
        if "MCX" in exchanges and up is not None:
            try:
                rows = await up.commodity_underlyings()
            except BrokerError as exc:
                log.warning("charts: could not load the MCX instruments: %s", exc)
                rows = []
            head_rows, tail_rows = [], []
            for inst in rows:
                und = (inst.underlying or inst.symbol).upper()
                if und == q or und.startswith(q):
                    head_rows.append((0 if und == q else 1, und, inst))
                elif q in und or (
                    len(q) >= 3
                    and (q in inst.symbol.upper() or q in (inst.display_name or "").upper())
                ):
                    tail_rows.append((2, und, inst))
            head_rows.sort(key=lambda r: r[:2])
            tail_rows.sort(key=lambda r: r[:2])
            for bucket, und, inst in (head_rows + tail_rows)[:cap]:
                ref = SymbolRef(
                    id=f"mcx:{und}",
                    label=f"{und} — MCX near month {inst.expiry}",
                    group="MCX commodity",
                )
                (head if bucket < 2 else tail).append(ref)

        out = head + nse_out + bse_out + tail
        return out[:limit]

    def _equity_hits(self, equities: dict, exchange: str, q: str) -> list:
        """Cash names of one exchange matching q: exact ticker, prefix, substring, then
        company name; liquid names first inside each group (as the NSE search does)."""
        hits = []
        for (exch, symbol), inst in equities.items():
            if exch != exchange or self._is_test(symbol):
                continue
            if not q or symbol == q:
                bucket = 0
            elif symbol.startswith(q):
                bucket = 1
            elif q in symbol:
                bucket = 2
            elif len(q) >= 3 and q in (inst.display_name or "").upper():
                bucket = 3
            else:
                continue
            hits.append((bucket, self._liquidity_rank(symbol), symbol, inst))
        hits.sort(key=lambda row: row[:3])
        return [row[3] for row in hits]

    def _basket_refs(self, q: str) -> list[SymbolRef]:
        """Saved baskets by name. Otherwise a basket is reachable only by its id."""
        if self.baskets is None:
            return []
        out: list[SymbolRef] = []
        for basket in self.baskets.all():
            if q and q not in basket.name.upper() and q not in basket.id.upper():
                continue
            out.append(
                SymbolRef(
                    id=f"basket:{basket.id}",
                    label=f"{basket.name} (basket, {len(basket.legs)} legs)",
                    group="Baskets",
                )
            )
        return out[:10]

    async def _contract_refs(
        self, underlying: str, strike_text: str, opt_type: str | None, limit: int = 24
    ) -> list[SymbolRef]:
        """Option contracts whose strike starts with what was typed."""
        from .options import active_expiries

        if not self._has_options(underlying):
            return []
        try:
            contracts = await self.broker.option_chain_instruments(underlying, None)
        except BrokerError:
            return []
        out: list[SymbolRef] = []
        for expiry in active_expiries([c.expiry for c in contracts if c.expiry])[:2]:
            for c in contracts:
                if c.expiry != expiry or not c.strike or c.option_type not in ("CE", "PE"):
                    continue
                if opt_type and c.option_type != opt_type:
                    continue
                if not f"{c.strike:g}".startswith(strike_text):
                    continue
                out.append(
                    SymbolRef(
                        id=f"opt:{underlying}:{expiry}:{c.strike:g}:{c.option_type}",
                        label=f"{underlying} {c.strike:g} {c.option_type} {expiry}",
                        group=f"{underlying} options {expiry}",
                    )
                )
                if len(out) >= limit:
                    return out
        return out

    async def _option_refs(self, underlying: str, span: int = 4) -> list[SymbolRef]:
        """ATM +/- `span` strikes for the nearest expiry, both sides.

        Best-effort: a missing chain or spot price just means no option entries in
        the dropdown, never a failed search.
        """
        from .options import active_expiries, infer_strike_step, reference_price

        if not self._has_options(underlying):
            return []

        try:
            contracts = await self.broker.option_chain_instruments(underlying, None)
        except BrokerError:
            return []
        expiries = active_expiries([c.expiry for c in contracts if c.expiry])
        if not expiries:
            return []
        expiry = expiries[0]
        legs = [c for c in contracts if c.expiry == expiry]

        try:
            spot, _ = await reference_price(self.broker, underlying, "index")
        except BrokerError:
            return []

        strikes = sorted({c.strike for c in legs if c.strike})
        if not strikes:
            return []
        step = infer_strike_step(strikes)
        atm = min(strikes, key=lambda s: abs(s - spot))

        by_key = {
            (round(c.strike, 4), c.option_type): c
            for c in legs
            if c.strike and c.option_type in ("CE", "PE")
        }
        out: list[SymbolRef] = []
        for opt_type in ("CE", "PE"):
            for k in range(-span, span + 1):
                strike = round(atm + k * step, 4)
                if (strike, opt_type) not in by_key:
                    continue
                tag = "ATM" if k == 0 else f"{'+' if k > 0 else ''}{k}"
                out.append(
                    SymbolRef(
                        id=f"opt:{underlying}:{expiry}:{strike:g}:{opt_type}",
                        label=f"{underlying} {strike:g} {opt_type} {expiry} ({tag})",
                        group=f"{underlying} options {expiry}",
                    )
                )
        return out

    # Exchange test/dummy series that should never appear in a picker.
    _TEST_PATTERNS = ("NSETEST", "TESTSC", "DUMMY", "-RE", "ZZZZ")

    @classmethod
    def _is_test(cls, symbol: str) -> bool:
        return any(p in symbol for p in cls._TEST_PATTERNS)

    # Shown first when no search text has been typed.
    POPULAR = (
        "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "ITC", "LT",
        "AXISBANK", "KOTAKBANK", "BHARTIARTL", "HINDUNILVR", "BAJFINANCE", "MARUTI",
        "ASIANPAINT", "TATAMOTORS", "TATASTEEL", "WIPRO", "HCLTECH", "SUNPHARMA",
        "ADANIENT", "TITAN", "ULTRACEMCO", "POWERGRID", "NTPC", "COALINDIA",
        "ONGC", "M&M", "NESTLEIND", "JSWSTEEL",
    )

    @classmethod
    def _liquidity_rank(cls, symbol: str) -> int:
        try:
            return cls.POPULAR.index(symbol)
        except ValueError:
            return len(cls.POPULAR)

    def _nodes(self) -> Iterable:
        """Walk the broker graph; wrappers nest several levels deep."""
        from .brokers import broker_nodes

        return broker_nodes(self.broker)

    async def _warm_instruments(self) -> None:
        """Make sure an instrument master is loaded before reading its indexes.

        The masters load lazily on first use, so a fresh process that has not yet
        fetched a candle would otherwise report an empty symbol list.
        """
        for node in self._nodes():
            for attr in ("instruments", "scrips"):
                holder = getattr(node, attr, None)
                ensure = getattr(holder, "ensure", None)
                client = getattr(node, "client", None)
                if ensure is None or client is None or getattr(holder, "equities", None):
                    continue
                try:
                    await ensure(client)
                except BrokerError as exc:
                    log.warning("charts: could not load %s instruments: %s", node.name, exc)

    def _equity_index(self) -> dict:
        """Find the equity map on whichever broker is wrapped, however it is nested."""
        for node in self._nodes():
            for attr in ("instruments", "scrips"):
                equities = getattr(getattr(node, attr, None), "equities", None)
                if equities:
                    return equities
        return {}

    def _futures_index(self) -> dict:
        for node in self._nodes():
            for attr in ("instruments", "scrips"):
                futures = getattr(getattr(node, attr, None), "futures", None)
                if futures:
                    return futures
        return {}

    def _options_index(self) -> dict:
        for node in self._nodes():
            for attr in ("instruments", "scrips"):
                found = getattr(getattr(node, attr, None), "options", None)
                if found:
                    return found
        return {}

    def _has_options(self, underlying: str) -> bool:
        index = self._options_index()
        if index:
            return underlying.upper() in index
        # No instrument master at all (synthetic feed): only the indices make sense,
        # otherwise every typed word would conjure a fake chain.
        return underlying.upper() in self.INDEX_NAMES

    def option_underlyings(self) -> list[str]:
        """Every underlying with listed options, indices first."""
        index = self._options_index()
        names = sorted(index) if index else list(self.INDEX_NAMES)
        head = [n for n in self.INDEX_NAMES if n in names]
        return head + [n for n in names if n not in head]

    def _futures_for(self, underlying: str) -> list:
        """Tradable futures for an underlying, nearest expiry first.

        Contracts that have already settled are excluded, otherwise the picker would
        default to an expired series printing a stale price.
        """
        from .options import active_expiries

        rows = self._futures_index().get(underlying.upper(), [])
        live = set(active_expiries([f.expiry for f in rows if f.expiry]))
        usable = [f for f in rows if f.expiry in live]
        return sorted(usable or rows, key=lambda f: f.expiry or "")

    async def _resolve(self, symbol: str, *, for_data: bool = False):
        """A chart symbol id -> an instrument. `for_data` (candles and meta only) lets a
        BSE equity the engine cannot resolve fall back to the Upstox BSE master, so it
        can be charted; orders, baskets and watches keep the engine's resolution."""
        kind, _, rest = symbol.partition(":")
        if kind == "eq":
            exchange, _, name = rest.partition(":")
            if for_data and (exchange or "NSE").upper() == "BSE":
                return await self._resolve_bse_data(name)
            return await self.broker.resolve_equity(name, exchange or "NSE")
        if kind == "mcx":
            # mcx:<UNDERLYING>[:<YYYY-MM-DD>] - defaults to the near month
            from .brokers import find_upstox

            und, _, expiry = rest.partition(":")
            up = find_upstox(self.broker)
            if up is None:
                raise BrokerError("MCX symbols need the Upstox data provider")
            return await up.resolve_commodity(und, expiry or None)
        if kind == "idx":
            inst = await self.broker.index_instrument(rest)
            if inst is None:
                raise BrokerError(f"no index instrument for {rest}")
            return inst
        if kind == "opt":
            # opt:<UNDERLYING>:<EXPIRY>:<STRIKE>:<CE|PE>
            parts = rest.split(":")
            if len(parts) != 4:
                raise BrokerError(f"malformed option symbol '{symbol}'")
            underlying, expiry, strike, opt_type = parts
            contracts = await self.broker.option_chain_instruments(underlying, expiry or None)
            target = float(strike)
            for c in contracts:
                if c.option_type == opt_type and c.strike and abs(c.strike - target) < 1e-6:
                    return c
            raise BrokerError(f"no contract {underlying} {strike} {opt_type} @ {expiry}")
        if kind == "fut":
            # fut:<UNDERLYING>[:<EXPIRY>] - defaults to the near month
            und, _, expiry = rest.partition(":")
            rows = self._futures_for(und)
            if not rows:
                raise BrokerError(
                    f"no futures contract found for {und}. The instrument master may not "
                    "list it, or F&O may not be available on this data source."
                )
            if expiry:
                for f in rows:
                    if f.expiry == expiry:
                        return f
                raise BrokerError(f"no {und} future expiring {expiry}")
            return rows[0]
        # Bare text is treated as an NSE equity symbol.
        return await self.broker.resolve_equity(symbol.upper(), "NSE")

    async def _resolve_bse_data(self, name: str):
        """A BSE equity for candles: the engine's instrument when it carries a data key,
        else with the key from the Upstox BSE master (or that master's instrument)."""
        from .brokers import find_upstox

        inst = None
        error: BrokerError | None = None
        try:
            inst = await self.broker.resolve_equity(name, "BSE")
        except BrokerError as exc:
            error = exc
        if inst is not None and inst.data_key:
            return inst
        up = find_upstox(self.broker)
        if up is None:
            if inst is not None:
                return inst
            raise error  # type: ignore[misc]
        try:
            bse = await up.lookup_equity(name, "BSE")
        except BrokerError:
            if inst is not None:
                return inst
            raise
        return dataclasses.replace(inst, data_key=bse.data_key) if inst is not None else bse

    async def candles(self, symbol: str, timeframe: str, bars: int = DEFAULT_BARS) -> list[Bar]:
        minutes = tf_table.minutes_of(timeframe)
        if minutes is None:
            raise BrokerError(
                f"unsupported timeframe '{timeframe}'. Available: "
                f"{', '.join(t for t, _ in TIMEFRAMES)}"
            )
        if symbol.startswith("basket:"):
            return await self._basket_candles(symbol.split(":", 1)[1], timeframe, bars)
        instrument = await self._resolve(symbol, for_data=True)
        series = await tf_table.load_series(self.broker, instrument, minutes, bars=bars)
        # The forming candle is kept here on purpose: a chart should show the bar
        # being built, unlike the strategy which only ever acts on closed bars.
        return _to_bars(series, bars)

    async def _basket_candles(
        self, basket_id: str, timeframe: str, bars: int
    ) -> list[Bar]:
        """The basket's combined premium, chartable like any other symbol.

        In points, not rupees: each leg is weighted by its lots reduced by their common
        divisor (baskets.unit_weights), so a one-lot straddle charts as the sum of the
        two premiums and a spread as their difference.
        """
        from .baskets import combine, leg_profile, unit_weights

        if self.baskets is None:
            raise BrokerError("no basket registry is attached to this data source")
        try:
            basket = self.baskets.get(basket_id)
        except ValueError as exc:
            raise BrokerError(str(exc)) from exc

        lots: list[float] = []
        fetched: list[list[Bar]] = []
        for leg in basket.legs:
            leg_bars = await self.candles(leg.symbol, timeframe, bars)
            if not leg_bars:
                raise BrokerError(f"no data for basket leg {leg.symbol}")
            try:
                lot = max(1, int((await self._resolve(leg.symbol)).lot_size or 1))
            except BrokerError:
                lot = 1
            lots.append(leg.quantity / lot)
            fetched.append(leg_bars)
        legs = [
            (leg.sign * weight, leg_bars)
            for leg, weight, leg_bars in zip(basket.legs, unit_weights(lots), fetched)
        ]

        # One underlying (a straddle, a spread, a hedged future): value the combo at
        # the underlying's high and low for a realistic range. Mixed underlyings
        # have no shared moment, so they keep the widest bound.
        profiles = [leg_profile(leg.symbol) for leg in basket.legs]
        same = len({und for und, _ in profiles}) == 1
        merged = combine(legs, [up for _, up in profiles] if same else None)
        if not merged:
            raise BrokerError(
                "basket legs have no overlapping candles; they may trade different "
                "sessions or one leg is illiquid"
            )
        return merged[-bars:] if len(merged) > bars else merged

    async def meta(self, symbol: str) -> dict:
        if symbol.startswith("basket:") and self.baskets is not None:
            try:
                basket = self.baskets.get(symbol.split(":", 1)[1])
            except ValueError as exc:
                raise BrokerError(str(exc)) from exc
            return {
                "symbol": symbol,
                "display_name": f"{basket.name} ({len(basket.legs)} legs)",
                "segment": "BASKET",
                "tick_size": 0.05,
                "lot_size": 1,
                "legs": [l.as_dict() for l in basket.legs],
            }
        instrument = await self._resolve(symbol, for_data=True)
        return {
            "symbol": instrument.symbol,
            "display_name": instrument.display_name,
            "segment": instrument.segment,
            "tick_size": instrument.tick_size,
            "lot_size": instrument.lot_size,
            "expiry": instrument.expiry,
            "strike": instrument.strike,
            "option_type": instrument.option_type,
        }


# --------------------------------------------------------- example: add your own
#
# Sketch for a second provider. Uncomment, fill in, and it appears in the dropdown
# with no other changes anywhere in the project.
#
# @register("binance", label="Binance spot")
# class BinanceSource(DataSource):
#     INTERVALS = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
#                  "1h": "1h", "2h": "2h", "1D": "1d", "1W": "1w", "1M": "1M"}
#
#     def __init__(self, **_ignored):
#         import httpx
#         self._client = httpx.AsyncClient(base_url="https://api.binance.com", timeout=20.0)
#
#     async def search(self, query, limit=40):
#         data = (await self._client.get("/api/v3/exchangeInfo")).json()
#         q = (query or "").upper()
#         return [
#             SymbolRef(id=s["symbol"], label=s["symbol"], group="Binance")
#             for s in data["symbols"] if not q or q in s["symbol"]
#         ][:limit]
#
#     async def candles(self, symbol, timeframe, bars=DEFAULT_BARS):
#         rows = (await self._client.get("/api/v3/klines", params={
#             "symbol": symbol, "interval": self.INTERVALS[timeframe], "limit": bars,
#         })).json()
#         return [
#             Bar(time=int(r[0] // 1000), open=float(r[1]), high=float(r[2]),
#                 low=float(r[3]), close=float(r[4]), volume=float(r[5]))
#             for r in rows
#         ]
#
#     async def close(self):
#         await self._client.aclose()
