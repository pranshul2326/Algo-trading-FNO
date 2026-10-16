"""Upstox market-data provider. Free, and candles need no credentials at all.

Verified against the live API on 2026-09-29:

  GET /v3/historical-candle/intraday/{key}/minutes/1        -> today, no auth
  GET /v3/historical-candle/{key}/minutes/1/{to}/{from}     -> prior days, no auth
  GET /v3/market-quote/ltp?instrument_key=...               -> needs an access token

The candle endpoints are documented as "No authorization required" and behave that
way, so this works with zero setup. An access token is optional and only buys you a
true tick-level LTP; without one the last 1-minute close is used instead, which lags
by under a minute.

Instrument identity: Upstox keys look like `NSE_EQ|INE002A01018` (equity, by ISIN),
`NSE_FO|74365` (derivatives, by exchange token) and `NSE_INDEX|Nifty 50`. Crucially
the derivative/equity `exchange_token` is the same number Dhan uses as `security_id`
(RELIANCE 2885, NIFTY 25000 CE 74365, both verified), so instruments resolved through
Dhan for order placement can be translated here without any fuzzy matching.

This class is data-only. Every trading method raises, on purpose - pair it with an
execution broker via CompositeBroker.
"""

from __future__ import annotations

import asyncio
import calendar
import gzip
import json
import logging
import math
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

from ..candles import DAY, Candle, CandleSeries
from ..models import Instrument
from ..ratelimit import RequestLedger, TokenBucket
from ..timeutil import IST, mcx_close_time, now_ist, previous_trading_day, session_open, to_ist
from .base import Broker, BrokerError, BrokerPosition, OrderState, PlacedOrder

log = logging.getLogger(__name__)

API_BASE = "https://api.upstox.com"
INSTRUMENT_URLS = {
    "NSE": "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    "BSE": "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz",
    "MCX": "https://assets.upstox.com/market-quote/instruments/exchange/MCX.json.gz",
}

# Upstox segment -> the engine's segment vocabulary (which follows Dhan's).
SEGMENT_TO_ENGINE = {
    "NSE_EQ": "NSE_EQ",
    "NSE_FO": "NSE_FNO",
    "NSE_INDEX": "IDX_I",
    "BSE_EQ": "BSE_EQ",
    "BSE_FO": "BSE_FNO",
    "BSE_INDEX": "IDX_I",
    "NCD_FO": "NSE_CURRENCY",
    "BCD_FO": "BSE_CURRENCY",
    "MCX_FO": "MCX_COMM",
}
# Which engine segments share an exchange_token namespace, for cross-broker mapping.
TOKEN_NAMESPACES = {"NSE_EQ", "NSE_FNO", "BSE_EQ", "BSE_FNO"}

OPTION_TYPES = {"CE", "PE"}
EQUITY_TYPES = {"EQ", "BE"}
# The BSE master files cash equities under their BSE group as instrument_type.
BSE_EQUITY_GROUPS = {"A", "B", "T", "X", "XT", "Z", "ZP", "M", "MS", "MT", "P", "TS"}

# Request accounting. Every HTTP request to the Upstox API is recorded in
# UPSTOX_REQUESTS (shared by every UpstoxData in the process) under REQUEST_TAG's
# value ("app" unless a scan sets its own), and counted in REQUEST_COUNTER's list
# when a budgeted scanner call has set one.
REQUEST_TAG: ContextVar[str] = ContextVar("upstox_request_tag", default="app")
REQUEST_COUNTER: ContextVar[list[int] | None] = ContextVar("upstox_request_counter", default=None)
UPSTOX_REQUESTS = RequestLedger(1800.0)
# Months one historical request may span: up to 15-minute candles, and longer ones.
SPAN_MONTHS = {"short": 1, "long": 3}
DAY_SPAN_DAYS = 3649          # a daily request covers [to - 3,649 days, to]


def months_back(day: date, months: int) -> date:
    """The same day of the month `months` earlier, clamped to that month's length:
    months_back(2026-03-31, 1) = 2026-02-28."""
    index = day.year * 12 + (day.month - 1) - int(months)
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def request_pieces(interval_minutes: int, start: date, end: date) -> list[tuple[date, date]]:
    """Fewest (from, to) pieces Upstox accepts for [start, end], newest piece first:
    DAY: from >= to - 3,649 days; <= 15 min: from >= months_back(to, 1);
    > 15 min: from >= months_back(to, 3). Each piece starts at max(start, that bound);
    the next piece ends the day before."""
    out: list[tuple[date, date]] = []
    to = end
    while to >= start:
        if interval_minutes >= DAY:
            bound = to - timedelta(days=DAY_SPAN_DAYS)
        elif interval_minutes <= 15:
            bound = months_back(to, SPAN_MONTHS["short"])
        else:
            bound = months_back(to, SPAN_MONTHS["long"])
        frm = max(start, bound)
        out.append((frm, to))
        to = frm - timedelta(days=1)
    return out

# A browser-ish agent: the asset host rejects some default clients.
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "matheran/0.1 (+https://localhost) python-httpx",
}


def _ms_to_date(value) -> str | None:
    """Upstox expiry timestamps are epoch milliseconds."""
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, IST).date().isoformat()


class UpstoxInstruments:
    """The BOD instrument dump, filtered and indexed. Refreshed once a day."""

    def __init__(
        self, cache_dir: Path, exchanges: tuple[str, ...] = ("NSE",), *, keep_options: bool = True
    ):
        self.cache_dir = Path(cache_dir)
        self.exchanges = exchanges
        self.keep_options = keep_options
        self.equities: dict[tuple[str, str], Instrument] = {}
        self.indices: dict[str, Instrument] = {}
        self.options: dict[str, list[Instrument]] = {}
        self.futures: dict[str, list[Instrument]] = {}
        self.key_by_token: dict[tuple[str, str], str] = {}
        self.by_key: dict[str, Instrument] = {}
        self.loaded_for: date | None = None
        self._lock = asyncio.Lock()

    def _path(self, exchange: str, day: date) -> Path:
        return self.cache_dir / f"upstox-{exchange}-{day.isoformat()}.json.gz"

    async def ensure(self, client: httpx.AsyncClient) -> None:
        today = now_ist().date()
        if self.loaded_for == today:
            return
        async with self._lock:
            if self.loaded_for == today:
                return
            paths: list[Path] = []
            for exchange in self.exchanges:
                path = self._path(exchange, today)
                if not path.exists():
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".part")
                    try:
                        log.info("upstox: downloading %s instruments", exchange)
                        resp = await client.get(
                            INSTRUMENT_URLS[exchange], timeout=120.0, headers=HEADERS
                        )
                        resp.raise_for_status()
                        tmp.write_bytes(resp.content)
                        tmp.replace(path)
                    except Exception as exc:  # noqa: BLE001
                        tmp.unlink(missing_ok=True)
                        stale = sorted(self.cache_dir.glob(f"upstox-{exchange}-*.json.gz"))
                        if not stale:
                            raise BrokerError(
                                f"could not fetch the Upstox {exchange} instrument list: {exc}"
                            ) from exc
                        path = stale[-1]
                        log.warning("upstox: download failed (%s), using %s", exc, path)
                    for old in sorted(self.cache_dir.glob(f"upstox-{exchange}-*.json.gz"))[:-3]:
                        old.unlink(missing_ok=True)
                paths.append(path)

            await asyncio.to_thread(self._parse, paths, today)
            self.loaded_for = today
            log.info(
                "upstox: instruments loaded - %d equities, %d indices, %d option underlyings",
                len(self.equities),
                len(self.indices),
                len(self.options),
            )

    def _parse(self, paths: list[Path], today: date) -> None:
        equities: dict[tuple[str, str], Instrument] = {}
        indices: dict[str, Instrument] = {}
        options: dict[str, list[Instrument]] = {}
        futures: dict[str, list[Instrument]] = {}
        key_by_token: dict[tuple[str, str], str] = {}
        by_key: dict[str, Instrument] = {}
        today_iso = today.isoformat()

        for path in paths:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                rows = json.load(fh)
            for row in rows:
                up_segment = str(row.get("segment") or "")
                segment = SEGMENT_TO_ENGINE.get(up_segment)
                if segment is None:
                    continue
                itype = str(row.get("instrument_type") or "")
                key = str(row.get("instrument_key") or "")
                symbol = str(row.get("trading_symbol") or "")
                if not key or not symbol:
                    continue
                if up_segment == "BSE_EQ":
                    # Cash equities are filed under their BSE group; the rest (F, G,
                    # IF, E, R: debt, ETFs and others) are not equities.
                    if itype not in EQUITY_TYPES and itype not in BSE_EQUITY_GROUPS:
                        continue
                    itype = "EQ"
                elif up_segment == "MCX_FO" and itype.startswith("FUT"):
                    itype = "FUTCOM" if str(row.get("underlying_type") or "") == "COM" else "FUTIDX"
                if not self.keep_options and itype in OPTION_TYPES:
                    continue

                token = str(row.get("exchange_token") or "")
                tick = float(row.get("tick_size") or 0.0) / 100.0  # dump is in paise
                if tick <= 0:
                    tick = 0.05
                lot = int(row.get("lot_size") or 1) or 1
                expiry = _ms_to_date(row.get("expiry"))
                strike = row.get("strike_price")

                inst = Instrument(
                    security_id=token or key,
                    symbol=symbol,
                    segment=segment,
                    instrument_type=itype,
                    display_name=str(row.get("name") or symbol),
                    lot_size=max(1, lot),
                    tick_size=tick,
                    expiry=expiry,
                    strike=float(strike) if strike else None,
                    option_type=itype if itype in OPTION_TYPES else None,
                    underlying=str(row.get("underlying_symbol") or "") or None,
                    data_key=key,
                )

                by_key[key] = inst
                if token and segment in TOKEN_NAMESPACES:
                    key_by_token[(segment, token)] = key

                if up_segment in {"NSE_EQ", "BSE_EQ"} and itype in EQUITY_TYPES:
                    exchange = "NSE" if up_segment == "NSE_EQ" else "BSE"
                    prior = equities.get((exchange, symbol.upper()))
                    if prior is None or itype == "EQ":
                        equities[(exchange, symbol.upper())] = inst
                elif up_segment in {"NSE_INDEX", "BSE_INDEX"}:
                    indices.setdefault(symbol.upper(), inst)
                elif itype in OPTION_TYPES:
                    if not expiry or expiry < today_iso:
                        continue
                    underlying = (inst.underlying or "").upper()
                    if underlying:
                        options.setdefault(underlying, []).append(inst)
                elif itype.startswith("FUT"):
                    if not expiry or expiry < today_iso:
                        continue
                    underlying = (inst.underlying or "").upper()
                    if underlying:
                        futures.setdefault(underlying, []).append(inst)

        for rows_ in options.values():
            rows_.sort(key=lambda i: (i.expiry or "", i.strike or 0.0, i.option_type or ""))
        for rows_ in futures.values():
            rows_.sort(key=lambda i: i.expiry or "")

        self.equities = equities
        self.indices = indices
        self.options = options
        self.futures = futures
        self.key_by_token = key_by_token
        self.by_key = by_key


class UpstoxData(Broker):
    name = "upstox"
    supports_live_orders = False

    def __init__(
        self,
        *,
        cache_dir: Path,
        access_token: str | None = None,
        exchanges: tuple[str, ...] = ("NSE",),
    ):
        self.access_token = access_token or None
        self.instruments = UpstoxInstruments(cache_dir, exchanges)
        self._client: httpx.AsyncClient | None = None
        # Upstox publishes 50/s, 500/min and 2000 per 30 min for candle APIs. 10/s
        # keeps a full option-chain load to a few seconds while staying far inside
        # the per-second limit; the 45 s candle cache is what protects the 30-minute
        # budget when the chain page auto-refreshes.
        self._bucket = TokenBucket(10, burst=10, name="upstox")
        self._candle_cache: dict[str, tuple[datetime, CandleSeries]] = {}
        self._history_cache: dict[tuple[str, str, str], list[Candle]] = {}
        # BSE / MCX masters, loaded only when the scanner or the charts need them.
        self._extra: dict[str, UpstoxInstruments] = {}
        self._extra_lock = asyncio.Lock()
        # The scanner's today fetches, keyed (instrument key, step): 45 s TTL.
        self._today_cache: dict[tuple[str, int], tuple[datetime, CandleSeries]] = {}

    @property
    def data_source(self) -> str:
        return "upstox"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = dict(HEADERS)
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            self._client = httpx.AsyncClient(
                base_url=API_BASE, timeout=httpx.Timeout(30.0, connect=10.0), headers=headers
            )
        return self._client

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, params: dict | None = None, attempts: int = 3) -> dict:
        """GET with a short retry, because a scan fires a dozen requests at once and
        an occasional connection reset should not blank out a row."""
        last: Exception | None = None
        for attempt in range(attempts):
            await self._bucket.acquire()
            # Recorded and counted together, with no await in between.
            UPSTOX_REQUESTS.record(REQUEST_TAG.get())
            counter = REQUEST_COUNTER.get()
            if counter is not None:
                counter[0] += 1
            try:
                resp = await self.client.get(path, params=params)
                break
            except httpx.HTTPError as exc:
                last = exc
                if attempt == attempts - 1:
                    detail = str(exc) or type(exc).__name__
                    raise BrokerError(
                        f"network error calling Upstox {path}: {detail}", retryable=True
                    ) from exc
                await asyncio.sleep(0.4 * (2**attempt))
        else:  # pragma: no cover - loop always breaks or raises
            raise BrokerError(f"network error calling Upstox {path}: {last}", retryable=True)

        try:
            payload = resp.json() if resp.content else {}
        except ValueError:
            payload = {}

        if resp.status_code >= 300:
            code, message = "", resp.text[:200]
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                code = str(errors[0].get("errorCode") or "")
                message = str(errors[0].get("message") or message)
            if resp.status_code == 401:
                raise BrokerError(
                    "Upstox rejected the access token. Candles do not need one, but live "
                    f"LTP quotes do - generate a fresh token on the Upstox developer apps "
                    f"page or clear it to fall back to 1-minute closes. ({code})",
                    code=code or "401",
                    status=resp.status_code,
                )
            raise BrokerError(
                f"Upstox {path} failed ({resp.status_code} {code}): {message}",
                code=code,
                retryable=resp.status_code == 429 or resp.status_code >= 500,
                status=resp.status_code,
            )
        return payload if isinstance(payload, dict) else {}

    async def health(self) -> dict:
        await self.instruments.ensure(self.client)
        return {
            "broker": self.name,
            "role": "market data only",
            "candles_need_auth": False,
            "access_token_set": bool(self.access_token),
            "ltp_source": "live quote API" if self.access_token else "last 1-minute close",
            "equities": len(self.instruments.equities),
            "option_underlyings": len(self.instruments.options),
            "instruments_loaded_for": str(self.instruments.loaded_for),
            "extra_masters": sorted(self._extra),
        }

    # ------------------------------------------------------------ instruments
    async def resolve_equity(self, symbol: str, exchange: str = "NSE") -> Instrument:
        await self.instruments.ensure(self.client)
        inst = self.instruments.equities.get((exchange.upper(), symbol.upper()))
        if inst is None:
            raise BrokerError(f"{symbol} not found in the Upstox {exchange} cash segment")
        return inst

    # Upstox indexes spot by trading_symbol, which already matches what people type
    # (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 all verified present).
    # These aliases cover the other names the same index goes by.
    INDEX_ALIASES = {
        "NIFTY50": "NIFTY",
        "NIFTY 50": "NIFTY",
        "NIFTYBANK": "BANKNIFTY",
        "NIFTY BANK": "BANKNIFTY",
        "NIFTY FIN SERVICE": "FINNIFTY",
        "NIFTY MID SELECT": "MIDCPNIFTY",
        "NIFTY NEXT 50": "NIFTYNXT50",
    }

    async def index_instrument(self, underlying: str) -> Instrument | None:
        await self.instruments.ensure(self.client)
        name = underlying.upper()
        name = self.INDEX_ALIASES.get(name, name)
        return self.instruments.indices.get(name)

    async def option_chain_instruments(
        self, underlying: str, expiry: str | None = None
    ) -> list[Instrument]:
        await self.instruments.ensure(self.client)
        rows = self.instruments.options.get(underlying.upper(), [])
        if not rows:
            raise BrokerError(f"no live Upstox option contracts found for {underlying}")
        if expiry:
            rows = [r for r in rows if r.expiry == expiry]
            if not rows:
                raise BrokerError(f"no {underlying} contracts expiring on {expiry}")
        return rows

    async def expiries(self, underlying: str) -> list[str]:
        await self.instruments.ensure(self.client)
        rows = self.instruments.options.get(underlying.upper(), [])
        return sorted({r.expiry for r in rows if r.expiry})

    async def data_key_for(self, instrument: Instrument) -> str:
        """Translate any instrument into an Upstox instrument_key.

        Instruments resolved through Dhan carry its security_id, which is the same
        exchange token Upstox publishes, so the mapping is exact rather than fuzzy.
        """
        if instrument.data_key:
            return instrument.data_key

        await self.instruments.ensure(self.client)

        if instrument.segment in TOKEN_NAMESPACES:
            key = self.instruments.key_by_token.get(
                (instrument.segment, str(instrument.security_id))
            )
            if key:
                return key

        if instrument.segment == "IDX_I" or instrument.instrument_type == "INDEX":
            idx = self.instruments.indices.get(instrument.symbol.upper())
            if idx is not None and idx.data_key:
                return idx.data_key

        if instrument.instrument_type in {"EQUITY", "EQ", "BE"}:
            exchange = "BSE" if instrument.segment.startswith("BSE") else "NSE"
            eq = self.instruments.equities.get((exchange, instrument.symbol.upper()))
            if eq is not None and eq.data_key:
                return eq.data_key

        raise BrokerError(
            f"could not map {instrument.symbol} ({instrument.segment} "
            f"id={instrument.security_id}) to an Upstox instrument key"
        )

    # ------------------------------------------- extra masters (data-only lookups)
    async def exchange_instruments(self, exchange: str) -> UpstoxInstruments:
        """The instrument master of one exchange. NSE is the engine's own; BSE and MCX
        are loaded lazily (without options) the first time something asks for them."""
        exchange = str(exchange or "").upper()
        if exchange == "NSE":
            await self.instruments.ensure(self.client)
            return self.instruments
        if exchange not in {"BSE", "MCX"}:
            raise BrokerError(f"unknown exchange {exchange!r}: use NSE, BSE or MCX")
        async with self._extra_lock:
            holder = self._extra.get(exchange)
            if holder is None:
                holder = UpstoxInstruments(
                    self.instruments.cache_dir, (exchange,), keep_options=False
                )
                self._extra[exchange] = holder
        await holder.ensure(self.client)
        return holder

    async def lookup_equity(self, symbol: str, exchange: str = "NSE") -> Instrument:
        """A cash equity with its data_key set, for the scanner and the charts' data
        path; never used by the engine (resolve_equity is the engine's path)."""
        exchange = str(exchange or "").upper()
        if exchange not in {"NSE", "BSE"}:
            raise BrokerError(f"unknown cash exchange {exchange!r}: use NSE or BSE")
        holder = await self.exchange_instruments(exchange)
        inst = holder.equities.get((exchange, str(symbol).upper()))
        if inst is None:
            raise BrokerError(f"{symbol} not found in the Upstox {exchange} cash segment")
        return inst

    @staticmethod
    def _near_month(rows: list[Instrument]) -> list[Instrument]:
        """The rows of the nearest MCX expiry still trading (DST-aware close)."""
        from ..options import active_expiries

        today = now_ist().date()
        live = active_expiries(
            [r.expiry for r in rows if r.expiry], "MCX_COMM", close_time=mcx_close_time(today)
        )
        if not live:
            return []
        return [r for r in rows if r.expiry == live[0]]

    async def resolve_commodity(self, underlying: str, expiry: str | None = None) -> Instrument:
        """An MCX future of `underlying`: the near month, or the given expiry."""
        holder = await self.exchange_instruments("MCX")
        name = str(underlying or "").upper()
        rows = holder.futures.get(name, [])
        if expiry:
            rows = [r for r in rows if r.expiry == expiry]
        else:
            rows = self._near_month(rows)
        if not rows:
            raise BrokerError(f"no live MCX future for {underlying}")
        return rows[0]

    async def commodity_underlyings(self) -> list[Instrument]:
        """One near-month commodity future (FUTCOM) per MCX underlying, by name."""
        holder = await self.exchange_instruments("MCX")
        out: list[Instrument] = []
        for name in sorted(holder.futures):
            rows = [r for r in holder.futures[name] if r.instrument_type == "FUTCOM"]
            near = self._near_month(rows)
            if near:
                out.append(near[0])
        return out

    # ----------------------------------------------------------- market data
    @staticmethod
    def _rows_to_candles(rows) -> list[Candle]:
        out: list[Candle] = []
        for row in rows or []:
            try:
                ts = to_ist(datetime.fromisoformat(str(row[0])))
                out.append(
                    Candle(
                        ts=ts,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]) if len(row) > 5 else 0.0,
                        # row[6] is open interest, populated for derivatives.
                        oi=float(row[6]) if len(row) > 6 else 0.0,
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        return out

    async def _intraday(self, key: str, minutes: int) -> list[Candle]:
        path = f"/v3/historical-candle/intraday/{quote(key, safe='')}/minutes/{minutes}"
        data = await self._get(path)
        return self._rows_to_candles((data.get("data") or {}).get("candles"))

    async def _history(
        self,
        key: str,
        minutes: int,
        from_day: date,
        to_day: date,
        unit: str = "minutes",
        *,
        cache: bool = True,
        attempts: int = 3,
    ) -> list[Candle]:
        """With cache=False (the scanner's windows) the in-memory history cache is
        neither read nor written, so a scan cannot evict the engine's entries."""
        cache_key = (key, f"{unit}/{minutes}", from_day.isoformat(), to_day.isoformat())
        if cache and cache_key in self._history_cache:
            return self._history_cache[cache_key]
        path = (
            f"/v3/historical-candle/{quote(key, safe='')}/{unit}/{minutes}"
            f"/{to_day.isoformat()}/{from_day.isoformat()}"
        )
        data = await self._get(path, attempts=attempts)
        candles = self._rows_to_candles((data.get("data") or {}).get("candles"))
        if not cache:
            return candles
        # Closed sessions never change, so this can be cached for the whole run.
        self._history_cache[cache_key] = candles
        if len(self._history_cache) > 512:
            self._history_cache.pop(next(iter(self._history_cache)))
        return candles

    @staticmethod
    def _chunks(start: date, end: date, months: int) -> list[tuple[date, date]]:
        """[start, end] cut at calendar month (or quarter) boundaries.

        Upstox caps one request at a month of 1-15 minute candles and a quarter of
        longer ones (verified: two months of 1-minute or four of 30-minute is refused).
        Calendar-aligned pieces also keep the cache hitting from one day to the next.
        """
        out: list[tuple[date, date]] = []
        cur = start
        while cur <= end:
            first_month = ((cur.month - 1) // months) * months + 1
            nxt_month = first_month + months
            year = cur.year + (nxt_month - 1) // 12
            nxt = date(year, (nxt_month - 1) % 12 + 1, 1)
            piece_end = min(end, nxt - timedelta(days=1))
            out.append((cur, piece_end))
            cur = piece_end + timedelta(days=1)
        return out

    async def history_candles(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        """Completed sessions from the historical endpoint, which needs no token.

        Native candles are anchored at 09:15 like the engine's own resampling
        (verified for 15m, 30m, 1h and 2h), so they resample into any multiple.
        """
        if end < start:
            return CandleSeries([])
        key = await self.data_key_for(instrument)
        candles: list[Candle] = []
        if interval_minutes >= 1440:
            # Up to a decade per request; stamped 00:00, restamped at the session open.
            cur = start
            while cur <= end:
                piece_end = min(end, cur + timedelta(days=3600))
                rows = await self._history(key, 1, cur, piece_end, unit="days")
                for c in rows:
                    candles.append(Candle(
                        ts=session_open(instrument.segment, c.ts.date()), open=c.open,
                        high=c.high, low=c.low, close=c.close, volume=c.volume, oi=c.oi))
                cur = piece_end + timedelta(days=1)
        else:
            minutes = int(interval_minutes)
            months = 1 if minutes <= 15 else 3
            for a, b in self._chunks(start, end, months):
                try:
                    candles.extend(await self._history(key, minutes, a, b))
                except BrokerError as exc:
                    # A contract listed part-way through the range has nothing before
                    # its listing; the rest of the range is still worth having.
                    if exc.retryable:
                        raise
                    log.info("upstox: %s %s..%s unavailable (%s)", instrument.symbol, a, b, exc)
        candles.sort(key=lambda c: c.ts)
        deduped: list[Candle] = []
        for c in candles:
            if deduped and deduped[-1].ts == c.ts:
                deduped[-1] = c
            else:
                deduped.append(c)
        return CandleSeries(deduped)

    async def intraday_candles(
        self, instrument: Instrument, day: date, interval_minutes: int = 1
    ) -> CandleSeries:
        key = await self.data_key_for(instrument)
        cache_id = f"{key}:{interval_minutes}"
        now = now_ist()
        cached = self._candle_cache.get(cache_id)
        if cached and (now - cached[0]).total_seconds() < 45:
            return cached[1]

        # The historical endpoint excludes the current day (verified), so prior
        # sessions come from there and today comes from the intraday endpoint.
        start = previous_trading_day(day, 5)
        end = previous_trading_day(day, 1)
        candles: list[Candle] = []
        try:
            candles.extend(await self._history(key, interval_minutes, start, end))
        except BrokerError as exc:
            log.warning("upstox: history for %s unavailable (%s)", instrument.symbol, exc)

        if day >= now.date():
            candles.extend(await self._intraday(key, interval_minutes))
        else:
            candles.extend(await self._history(key, interval_minutes, day, day))

        candles.sort(key=lambda c: c.ts)
        deduped: list[Candle] = []
        for c in candles:
            if deduped and deduped[-1].ts == c.ts:
                deduped[-1] = c
            else:
                deduped.append(c)

        series = CandleSeries(deduped)
        self._candle_cache[cache_id] = (now, series)
        return series

    async def ltp(self, instruments: list[Instrument]) -> dict[str, float]:
        if not instruments:
            return {}

        keys: dict[str, Instrument] = {}
        for inst in instruments:
            try:
                keys[await self.data_key_for(inst)] = inst
            except BrokerError as exc:
                log.warning("upstox: %s", exc)

        if not keys:
            return {}

        if self.access_token:
            try:
                return await self._ltp_via_quote(keys)
            except BrokerError as exc:
                log.warning("upstox: quote API failed (%s), using 1-minute closes", exc)

        # No token: the freshest 1-minute close stands in for the LTP. It lags by
        # under a minute, and the protective stop resting at the execution broker
        # is what covers intra-minute moves.
        out: dict[str, float] = {}
        today = now_ist().date()
        for inst in keys.values():
            try:
                series = await self.intraday_candles(inst, today, 1)
            except BrokerError:
                continue
            if series:
                out[inst.security_id] = float(series.candles[-1].close)
        return out

    async def _ltp_via_quote(self, keys: dict[str, Instrument]) -> dict[str, float]:
        out: dict[str, float] = {}
        items = list(keys.items())
        for i in range(0, len(items), 400):  # endpoint accepts up to 500 keys
            chunk = items[i : i + 400]
            data = await self._get(
                "/v3/market-quote/ltp", params={"instrument_key": ",".join(k for k, _ in chunk)}
            )
            entries = data.get("data") or {}
            token_to_inst = {
                str((inst.data_key or key).split("|")[-1]): inst for key, inst in chunk
            }
            for payload in entries.values():
                if not isinstance(payload, dict):
                    continue
                price = payload.get("last_price")
                token = str(payload.get("instrument_token") or "")
                inst = token_to_inst.get(token.split("|")[-1])
                if inst is not None and price:
                    out[inst.security_id] = float(price)
        return out

    # ------------------------------------------------- scanner market data
    TODAY_TTL_SECONDS = 45
    TODAY_CACHE_MAX = 2000

    @staticmethod
    def _dedupe(candles: list[Candle]) -> list[Candle]:
        candles.sort(key=lambda c: c.ts)
        out: list[Candle] = []
        for c in candles:
            if out and out[-1].ts == c.ts:
                out[-1] = c
            else:
                out.append(c)
        return out

    def _prune_today_cache(self, now: datetime) -> None:
        cache = self._today_cache
        if len(cache) <= self.TODAY_CACHE_MAX:
            return
        for k in [k for k, (at, _) in cache.items()
                  if (now - at).total_seconds() >= self.TODAY_TTL_SECONDS]:
            del cache[k]
        while len(cache) > self.TODAY_CACHE_MAX:
            del cache[min(cache, key=lambda k: cache[k][0])]

    async def today_candles(
        self, instrument: Instrument, interval_minutes: int = 1, *, day: date | None = None
    ) -> CandleSeries:
        """Today's candles, the forming one included, in one request: at the coarsest of
        30, 15, 5 or 1 minutes that divides interval_minutes (the intervals the intraday
        endpoint serves), or one session candle (days/1) when interval_minutes >= DAY.
        The caller resamples. Only bars dated `day` (default today in IST) are returned,
        so a weekend or holiday answer is never mistaken for today. The engine's
        candle cache is reused when fresh but never written; a single attempt."""
        key = await self.data_key_for(instrument)
        interval = int(interval_minutes)
        if interval >= DAY:
            step = DAY
        else:
            step = max(s for s in (30, 15, 5, 1) if interval % s == 0)
        target = day or now_ist().date()
        now = now_ist()

        def of_day(series: CandleSeries) -> CandleSeries:
            return CandleSeries([c for c in series.candles if c.ts.date() == target])

        engine = self._candle_cache.get(f"{key}:{step}")
        if engine and (now - engine[0]).total_seconds() < self.TODAY_TTL_SECONDS:
            return of_day(engine[1])
        mine = self._today_cache.get((key, step))
        if mine and (now - mine[0]).total_seconds() < self.TODAY_TTL_SECONDS:
            return of_day(mine[1])

        unit = "days/1" if step >= DAY else f"minutes/{step}"
        path = f"/v3/historical-candle/intraday/{quote(key, safe='')}/{unit}"
        data = await self._get(path, attempts=1)
        candles = self._rows_to_candles((data.get("data") or {}).get("candles"))
        if step >= DAY:
            candles = [
                Candle(ts=session_open(instrument.segment, c.ts.date()), open=c.open,
                       high=c.high, low=c.low, close=c.close, volume=c.volume, oi=c.oi)
                for c in candles
            ]
        series = CandleSeries(self._dedupe(candles))
        self._today_cache[(key, step)] = (now, series)
        self._prune_today_cache(now)
        return of_day(series)

    async def history_window(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        """Completed sessions of [start, end] in the fewest pieces Upstox accepts
        (request_pieces), newest first, one attempt each, bypassing the in-memory
        history cache. Any error on a piece propagates, so a window never comes back
        with a silent hole (history_candles, the engine's path, skips and logs)."""
        if end < start:
            return CandleSeries([])
        key = await self.data_key_for(instrument)
        interval = int(interval_minutes)
        daily = interval >= DAY
        candles: list[Candle] = []
        for a, b in request_pieces(interval, start, end):
            if daily:
                rows = await self._history(key, 1, a, b, unit="days", cache=False, attempts=1)
                candles.extend(
                    Candle(ts=session_open(instrument.segment, c.ts.date()), open=c.open,
                           high=c.high, low=c.low, close=c.close, volume=c.volume, oi=c.oi)
                    for c in rows
                )
            else:
                candles.extend(
                    await self._history(key, interval, a, b, cache=False, attempts=1)
                )
        return CandleSeries(self._dedupe(candles))

    async def quote_ltp(self, instruments: list[Instrument]) -> dict[str, float]:
        """Last traded price keyed by the full Upstox instrument key, from
        /v3/market-quote/ltp only.

        One HTTP request (a single attempt), at most 400 instruments (ValueError above
        that; the caller batches). Never falls back to candles and never touches the
        candle or history caches. Raises BrokerError: no token (code NO_TOKEN, before
        any request), 401 (expired or invalid token), 429 and 5xx (retryable), network
        errors.

        Matching: an entry's instrument_token is documented as the full key, so it is
        matched exactly first; otherwise on (segment of the answer's key, the token's
        part after "|"), which keeps NSE_EQ|INE... and BSE_EQ|INE... apart.
        """
        if len(instruments) > 400:
            raise ValueError(f"quote_ltp takes at most 400 instruments, got {len(instruments)}")
        if not self.access_token:
            raise BrokerError(
                "live quotes need an Upstox access token; prices come from the candles",
                code="NO_TOKEN",
            )
        if not instruments:
            return {}
        keys = [await self.data_key_for(i) for i in instruments]
        data = await self._get(
            "/v3/market-quote/ltp", params={"instrument_key": ",".join(keys)}, attempts=1
        )
        wanted = set(keys)
        by_suffix = {(k.split("|")[0], k.split("|")[-1]): k for k in keys}
        entries = data.get("data") if isinstance(data, dict) else None
        out: dict[str, float] = {}
        for answer_key, entry in (entries.items() if isinstance(entries, dict) else ()):
            if not isinstance(entry, dict):
                continue
            token = str(entry.get("instrument_token") or "")
            key = token if token in wanted else by_suffix.get(
                (str(answer_key).split(":")[0], token.split("|")[-1])
            )
            price = entry.get("last_price")
            if (
                key
                and isinstance(price, (int, float))
                and not isinstance(price, bool)
                and math.isfinite(price)
                and price > 0
            ):
                out[key] = float(price)
        return out

    # --------------------------------------------------------------- trading
    _NO_TRADING = (
        "Upstox is configured here as a market-data provider only. Orders go to your "
        "execution broker - check broker.name in config.yaml."
    )

    async def place_order(self, **kwargs) -> PlacedOrder:
        raise BrokerError(self._NO_TRADING)

    async def order_state(self, broker_order_id: str) -> OrderState:
        raise BrokerError(self._NO_TRADING)

    async def cancel_order(self, broker_order_id: str) -> bool:
        raise BrokerError(self._NO_TRADING)

    async def positions(self) -> list[BrokerPosition]:
        return []
