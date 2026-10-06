"""Option chain selection and the ATM +/- OTM scan table."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from .brokers.base import Broker, BrokerError
from .candles import drop_forming, resample
from .config import StrategyConfig
from .candles import CandleSeries
from .models import Instrument, OiStats, OptionRow, Snapshot
from .strategy import Indicators, evaluate_entry
from .timeframes import load_series
from .timeutil import now_ist, session_close

log = logging.getLogger(__name__)

MAX_CONCURRENT_FETCHES = 4
BUILDUP_MINUTES = 5


def oi_stats(raw: CandleSeries, buildup_minutes: int = BUILDUP_MINUTES) -> OiStats:
    """Open interest now, versus the previous session, and over the last few minutes.

    Takes the 1-minute series so the buildup window is exact regardless of the
    timeframe the chart is drawn on.
    """
    if not raw:
        return OiStats(buildup_minutes=buildup_minutes)

    candles = raw.candles
    today = candles[-1].ts.date()
    todays = [c for c in candles if c.ts.date() == today]
    earlier = [c for c in candles if c.ts.date() < today]

    current = todays[-1].oi if todays else candles[-1].oi
    prev_close = earlier[-1].oi if earlier else 0.0
    change = current - prev_close if prev_close else 0.0
    change_pct = (change / prev_close * 100.0) if prev_close else 0.0

    # Walk back `buildup_minutes` of wall clock rather than a fixed bar count, so a
    # gap in the feed cannot silently stretch the window.
    buildup = 0.0
    if todays:
        cutoff = todays[-1].ts - timedelta(minutes=buildup_minutes)
        past = [c for c in todays if c.ts <= cutoff]
        if past:
            buildup = current - past[-1].oi

    return OiStats(
        oi=current,
        change=change,
        change_pct=change_pct,
        buildup=buildup,
        buildup_minutes=buildup_minutes,
        volume=sum(c.volume for c in todays),
        prev_close_oi=prev_close,
    )


@dataclass(slots=True)
class ChainSelection:
    underlying: str
    expiry: str
    reference: str          # "index" or "future"
    reference_symbol: str
    spot: float
    atm_strike: float
    strike_step: float
    instruments: list[tuple[Instrument, str]]  # (instrument, moneyness label)
    missing: list[str]  # requested legs with no listed contract
    expires_today: bool  # last trading day: theta is brutal, flag it to the operator


def active_expiries(expiries: Iterable[str], segment: str = "NSE_FNO") -> list[str]:
    """Expiries still worth trading, nearest first.

    Today's series is tradable right up to the close, but once the session has ended
    it is dead: every strike prints its residual value and no signal on it means
    anything. Shared by the chain scanner and the chart symbol picker so they never
    disagree about which expiry is current.
    """
    now = now_ist()
    today = now.date().isoformat()
    settled_today = now > session_close(segment, now.date())
    rows = sorted({e for e in expiries if e})
    if settled_today:
        return [e for e in rows if e > today]
    return [e for e in rows if e >= today]


def infer_strike_step(strikes: list[float]) -> float:
    """Most common gap between consecutive strikes. Chains contain wide-spaced
    far strikes, so the mode is more reliable than the minimum."""
    uniq = sorted({round(s, 4) for s in strikes if s and s > 0})
    if len(uniq) < 2:
        return 50.0
    gaps = Counter(round(b - a, 4) for a, b in zip(uniq, uniq[1:]) if b > a)
    if not gaps:
        return 50.0
    step, _count = gaps.most_common(1)[0]
    return float(step) if step > 0 else 50.0


async def reference_price(
    broker: Broker, underlying: str, reference: str = "index"
) -> tuple[float, str]:
    """Spot (or near-month future) price used to locate the ATM strike."""
    if reference == "future":
        futures = getattr(getattr(broker, "scrips", None), "futures", {}) or {}
        rows = futures.get(underlying.upper(), [])
        if rows:
            near = rows[0]
            prices = await broker.ltp([near])
            price = prices.get(near.security_id)
            if price:
                return price, near.symbol
        log.warning("options: no future found for %s, falling back to index spot", underlying)

    index = await broker.index_instrument(underlying)
    if index is None:
        # Stock options: the "spot" is the stock itself.
        try:
            index = await broker.resolve_equity(underlying, "NSE")
        except BrokerError:
            index = None
    if index is None:
        raise BrokerError(f"no index or stock price found for {underlying}")
    prices = await broker.ltp([index])
    price = prices.get(index.security_id)
    if not price:
        raise BrokerError(f"no spot price available for {underlying}")
    return price, index.symbol


async def select_chain(
    broker: Broker,
    underlying: str,
    *,
    expiry: str | None = None,
    otm_count: int = 5,
    reference: str = "index",
) -> ChainSelection:
    """ATM plus `otm_count` OTM strikes on each side: calls above, puts below."""
    underlying = underlying.upper()
    all_contracts = await broker.option_chain_instruments(underlying, None)

    available = sorted({c.expiry for c in all_contracts if c.expiry})
    if not available:
        raise BrokerError(f"no expiries available for {underlying}")
    if expiry in (None, "", "nearest"):
        candidates = active_expiries(available)
        chosen = candidates[0] if candidates else available[0]
        today = now_ist().date().isoformat()
        if chosen != today and today in available:
            log.info(
                "options: %s expiry %s has already settled, rolling to %s",
                underlying, today, chosen,
            )
    else:
        if expiry not in available:
            raise BrokerError(f"expiry {expiry} not available for {underlying}; have {available[:8]}")
        chosen = expiry

    contracts = [c for c in all_contracts if c.expiry == chosen]
    spot, ref_symbol = await reference_price(broker, underlying, reference)

    step = infer_strike_step([c.strike for c in contracts if c.strike])
    strikes = sorted({c.strike for c in contracts if c.strike})
    if not strikes:
        raise BrokerError(f"no strikes found for {underlying} {chosen}")
    atm = min(strikes, key=lambda s: abs(s - spot))

    by_key: dict[tuple[float, str], Instrument] = {}
    for c in contracts:
        if c.strike and c.option_type in {"CE", "PE"}:
            by_key[(round(c.strike, 4), c.option_type)] = c

    selected: list[tuple[Instrument, str]] = []
    missing: list[str] = []
    # Calls go OTM above the ATM strike, puts go OTM below it.
    for opt_type, direction in (("CE", 1), ("PE", -1)):
        for i in range(otm_count + 1):
            label = "ATM" if i == 0 else f"OTM+{i}"
            strike = round(atm + direction * i * step, 4)
            found = by_key.get((strike, opt_type))
            if found:
                selected.append((found, label))
            else:
                missing.append(f"{strike:g}{opt_type}")

    if not selected:
        raise BrokerError(
            f"could not build a chain around ATM {atm} for {underlying} {chosen} (step {step})"
        )
    if missing:
        log.warning(
            "options: %s %s has no listed contract for %s", underlying, chosen, ", ".join(missing)
        )

    return ChainSelection(
        underlying=underlying,
        expiry=chosen,
        reference=reference,
        reference_symbol=ref_symbol,
        spot=spot,
        atm_strike=atm,
        strike_step=step,
        instruments=selected,
        missing=missing,
        expires_today=chosen == now_ist().date().isoformat(),
    )


async def scan_chain(
    broker: Broker,
    selection: ChainSelection,
    cfg: StrategyConfig,
    *,
    timeframe_minutes: int = 1,
    adx_min: float | None = None,
    day: date | None = None,
) -> list[OptionRow]:
    """Build the display table and evaluate the entry gate for every leg."""
    day = day or now_ist().date()
    instruments = [inst for inst, _ in selection.instruments]

    try:
        prices = await broker.ltp(instruments)
    except BrokerError as exc:
        log.warning("options: LTP batch failed (%s), falling back to candle closes", exc)
        prices = {}

    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def one(inst: Instrument, label: str) -> OptionRow:
        async with sem:
            try:
                raw = await broker.intraday_candles(inst, day, 1)
                if timeframe_minutes >= 60:
                    # An hour and up reaches back past the 1-minute feed's six sessions.
                    series = await load_series(
                        broker, inst, timeframe_minutes,
                        bars=max(150, 3 * cfg.warmup_bars()),
                    )
                else:
                    series = resample(raw, timeframe_minutes, inst.segment)
            except BrokerError as exc:
                return OptionRow(
                    instrument=inst,
                    moneyness=label,
                    snapshot=Snapshot(ltp=prices.get(inst.security_id)),
                    price_above_vwap=False,
                    entry_ready=False,
                    checks={},
                    reasons=[],
                    oi=OiStats(),
                    error=str(exc),
                )

        closed, _forming = drop_forming(series, timeframe_minutes, now_ist(), inst.segment)
        ind = Indicators(closed, cfg)
        ltp = prices.get(inst.security_id)
        if ltp is None and closed:
            ltp = float(closed.close[-1])
        oi = oi_stats(raw)

        signal = evaluate_entry(
            ind,
            cfg,
            ltp=ltp,
            require_adx=True,
            adx_min=adx_min if adx_min is not None else cfg.adx_min,
        )
        snap = signal.snapshot
        above_vwap = bool(
            snap.vwap is not None and ltp is not None and ltp > snap.vwap
        )
        return OptionRow(
            instrument=inst,
            moneyness=label,
            snapshot=snap,
            price_above_vwap=above_vwap,
            entry_ready=signal.ready,
            checks=signal.checks,
            reasons=signal.reasons,
            oi=oi,
        )

    rows = await asyncio.gather(*(one(inst, label) for inst, label in selection.instruments))

    def sort_key(row: OptionRow) -> tuple:
        return (0 if row.instrument.option_type == "CE" else 1, row.instrument.strike or 0.0)

    return sorted(rows, key=sort_key)


# ----------------------------------------------------------------- full chain
# The scan above is ATM plus OTM on each side, for trading. The chain below is the
# classic calls | strike | puts page: every listed strike around the money, both
# sides, with open interest and what it has done over the last few minutes.

MAX_CHAIN_STRIKES_EACH_SIDE = 15
CHAIN_CONCURRENT_FETCHES = 8


def buildup_label(price_change: float | None, oi_change: float | None) -> str:
    """Standard option-chain reading of price direction against OI direction.

        price up,   OI up    Long Buildup     fresh longs being written
        price down, OI up    Short Buildup    fresh shorts being written
        price up,   OI down  Short Covering   shorts closing
        price down, OI down  Long Unwinding   longs closing

    Flat price or flat OI says nothing, so it gets no label.
    """
    if not price_change or not oi_change:
        return ""
    if price_change > 0:
        return "Long Buildup" if oi_change > 0 else "Short Covering"
    return "Short Buildup" if oi_change > 0 else "Long Unwinding"


@dataclass(slots=True)
class FullChain:
    underlying: str
    expiry: str
    expiries: list[str]
    reference_symbol: str
    spot: float
    atm_strike: float
    strike_step: float
    strikes: list[float]
    contracts: dict[tuple[float, str], Instrument]
    expires_today: bool


async def select_full_chain(
    broker: Broker,
    underlying: str,
    *,
    expiry: str | None = None,
    strikes_each_side: int = 8,
) -> FullChain:
    """Every listed strike within `strikes_each_side` of the ATM, calls and puts.

    Neighbours are taken from the listed strikes rather than ATM +/- k * step,
    because chains widen their spacing away from the money and a fixed step would
    ask for strikes that do not exist.
    """
    underlying = underlying.upper()
    strikes_each_side = max(1, min(int(strikes_each_side), MAX_CHAIN_STRIKES_EACH_SIDE))
    all_contracts = await broker.option_chain_instruments(underlying, None)

    available = sorted({c.expiry for c in all_contracts if c.expiry})
    if not available:
        raise BrokerError(f"no expiries available for {underlying}")
    live = active_expiries(available)
    if expiry in (None, "", "nearest"):
        chosen = live[0] if live else available[0]
    elif expiry not in available:
        raise BrokerError(f"expiry {expiry} not available for {underlying}; have {available[:8]}")
    else:
        chosen = expiry

    contracts = [
        c for c in all_contracts
        if c.expiry == chosen and c.strike and c.option_type in {"CE", "PE"}
    ]
    strikes_all = sorted({round(c.strike, 4) for c in contracts})
    if not strikes_all:
        raise BrokerError(f"no strikes found for {underlying} {chosen}")

    spot, ref_symbol = await reference_price(broker, underlying, "index")
    atm = min(strikes_all, key=lambda s: abs(s - spot))
    i = strikes_all.index(atm)
    window = strikes_all[max(0, i - strikes_each_side): i + strikes_each_side + 1]
    wanted = set(window)
    by_key = {
        (round(c.strike, 4), c.option_type): c
        for c in contracts
        if round(c.strike, 4) in wanted
    }
    return FullChain(
        underlying=underlying,
        expiry=chosen,
        expiries=live or available,
        reference_symbol=ref_symbol,
        spot=spot,
        atm_strike=atm,
        strike_step=infer_strike_step(strikes_all),
        strikes=window,
        contracts=by_key,
        expires_today=chosen == now_ist().date().isoformat(),
    )


def chain_quote(
    inst: Instrument,
    raw: CandleSeries | None,
    ltp: float | None,
    *,
    underlying: str,
    window_minutes: int = BUILDUP_MINUTES,
    error: str = "",
) -> dict:
    """One side of one strike: price, change, OI, OI change and the recent buildup."""
    oi = oi_stats(raw, window_minutes) if raw else OiStats(buildup_minutes=window_minutes)
    prev_close: float | None = None
    window_change: float | None = None
    last_ts = None
    price = ltp

    if raw:
        candles = raw.candles
        last_day = candles[-1].ts.date()
        todays = [c for c in candles if c.ts.date() == last_day]
        earlier = [c for c in candles if c.ts.date() < last_day]
        last = todays[-1] if todays else candles[-1]
        last_ts = last.ts
        if price is None or price <= 0:
            price = last.close
        if earlier:
            prev_close = earlier[-1].close
        # Same wall-clock window as the OI buildup, so the two always pair up.
        cutoff = last.ts - timedelta(minutes=window_minutes)
        past = [c for c in todays if c.ts <= cutoff]
        if past and price is not None:
            window_change = price - past[-1].close

    change = price - prev_close if (price is not None and prev_close) else None
    change_pct = change / prev_close * 100.0 if (change is not None and prev_close) else None
    strike = inst.strike or 0.0
    return {
        "security_id": inst.security_id,
        "segment": inst.segment,
        "symbol": inst.symbol,
        "strike": inst.strike,
        "option_type": inst.option_type,
        "expiry": inst.expiry,
        "lot_size": inst.lot_size,
        "chart_symbol": f"opt:{underlying}:{inst.expiry}:{strike:g}:{inst.option_type}",
        "ltp": round(price, 2) if price is not None else None,
        "prev_close": prev_close,
        "change": round(change, 2) if change is not None else None,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        **oi.as_dict(),
        "price_change_window": round(window_change, 2) if window_change is not None else None,
        "buildup": buildup_label(window_change, oi.buildup),
        "buildup_day": buildup_label(change, oi.change),
        "last_candle": last_ts.isoformat() if last_ts else None,
        "error": error,
    }


async def oi_chain(
    broker: Broker,
    chain: FullChain,
    *,
    window_minutes: int = BUILDUP_MINUTES,
    day: date | None = None,
) -> dict:
    """Fetch and tabulate the chain: one row per strike, calls and puts side by side."""
    day = day or now_ist().date()
    instruments = list(chain.contracts.values())
    sem = asyncio.Semaphore(CHAIN_CONCURRENT_FETCHES)

    async def fetch(inst: Instrument):
        async with sem:
            try:
                return inst, await broker.intraday_candles(inst, day, 1), ""
            except BrokerError as exc:
                return inst, None, str(exc)

    fetched = await asyncio.gather(*(fetch(inst) for inst in instruments))

    # Quotes second: the candles above are cached, so a provider that derives its
    # LTP from the last candle answers from memory, and one with a real quote API
    # makes a single batched call.
    try:
        prices = await broker.ltp([inst for inst, raw, _ in fetched if raw is not None])
    except BrokerError as exc:
        log.warning("options: chain LTP batch failed (%s), using candle closes", exc)
        prices = {}

    quotes: dict[tuple[float, str], dict] = {}
    for inst, raw, error in fetched:
        key = (round(inst.strike or 0.0, 4), inst.option_type or "")
        quotes[key] = chain_quote(
            inst,
            raw,
            prices.get(inst.security_id),
            underlying=chain.underlying,
            window_minutes=window_minutes,
            error=error,
        )

    rows = []
    totals = {"ce_oi": 0.0, "pe_oi": 0.0, "ce_oi_change": 0.0, "pe_oi_change": 0.0,
              "ce_volume": 0.0, "pe_volume": 0.0}
    as_of = None
    for strike in chain.strikes:
        ce = quotes.get((strike, "CE"))
        pe = quotes.get((strike, "PE"))
        for side, quote in (("ce", ce), ("pe", pe)):
            if quote is None:
                continue
            totals[f"{side}_oi"] += quote["oi"]
            totals[f"{side}_oi_change"] += quote["oi_change"]
            totals[f"{side}_volume"] += quote["volume"]
            if quote["last_candle"] and (as_of is None or quote["last_candle"] > as_of):
                as_of = quote["last_candle"]
        rows.append({"strike": strike, "atm": strike == chain.atm_strike, "ce": ce, "pe": pe})

    totals["pcr"] = round(totals["pe_oi"] / totals["ce_oi"], 3) if totals["ce_oi"] else None
    return {
        "underlying": chain.underlying,
        "expiry": chain.expiry,
        "expiries": chain.expiries,
        "reference_symbol": chain.reference_symbol,
        "spot": round(chain.spot, 2),
        "atm_strike": chain.atm_strike,
        "strike_step": chain.strike_step,
        "expires_today": chain.expires_today,
        "window_minutes": window_minutes,
        "rows": rows,
        "totals": totals,
        "as_of": as_of,
        "errors": sum(1 for _, raw, err in fetched if err),
    }
