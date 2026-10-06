"""DhanHQ v2 adapter.

Docs used: https://dhanhq.co/docs/v2/ (orders, historical-data, market-quote,
portfolio, instruments, annexure). Order placement requires a whitelisted static
IP on your Dhan account; read-only endpoints do not.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from ..candles import Candle, CandleSeries, build_candles
from ..models import Instrument, OrderStatus, OrderType, Side
from ..ratelimit import DailyQuota, TokenBucket
from ..timeutil import IST, now_ist, previous_trading_day, session_close, session_open
from .base import Broker, BrokerError, BrokerPosition, OrderState, PlacedOrder

log = logging.getLogger(__name__)

API_BASE = "https://api.dhan.co/v2"
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

SEGMENT_MAP = {
    ("NSE", "E"): "NSE_EQ",
    ("NSE", "D"): "NSE_FNO",
    ("NSE", "C"): "NSE_CURRENCY",
    ("NSE", "I"): "IDX_I",
    ("BSE", "E"): "BSE_EQ",
    ("BSE", "D"): "BSE_FNO",
    ("BSE", "C"): "BSE_CURRENCY",
    ("BSE", "I"): "IDX_I",
    ("MCX", "M"): "MCX_COMM",
}

WANTED_INSTRUMENTS = {"EQUITY", "INDEX", "OPTIDX", "OPTSTK", "FUTIDX", "FUTSTK"}
EQUITY_SERIES = {"EQ", "BE"}

# Data APIs are a paid add-on; Trading APIs are free. These codes mean "not subscribed".
DATA_SUBSCRIPTION_CODES = {"806", "DH-902"}
TOKEN_CODES = {"807", "808", "809", "DH-901"}

STATUS_MAP = {
    "TRANSIT": OrderStatus.PENDING,
    "PENDING": OrderStatus.OPEN,
    "TRIGGERED": OrderStatus.OPEN,
    "PART_TRADED": OrderStatus.PART_FILLED,
    "TRADED": OrderStatus.FILLED,
    "REJECTED": OrderStatus.REJECTED,
    "CANCELLED": OrderStatus.CANCELLED,
    "EXPIRED": OrderStatus.CANCELLED,
    "CLOSED": OrderStatus.FILLED,
}


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _num(value: str | None, default: float = 0.0) -> float:
    try:
        return float(_clean(value))
    except (TypeError, ValueError):
        return default


def _parse_option_symbol(trading_symbol: str) -> tuple[str, str] | None:
    """'BAJAJ-AUTO-Oct2026-12600-PE' -> ('BAJAJ-AUTO', 'PE').

    Parsed from the right so underlyings containing a hyphen stay intact.
    """
    parts = trading_symbol.split("-")
    if len(parts) < 4:
        return None
    option_type = parts[-1]
    if option_type not in {"CE", "PE"}:
        return None
    return "-".join(parts[:-3]), option_type


def _parse_future_symbol(trading_symbol: str) -> str | None:
    """'BANKNIFTY-Oct2026-FUT' -> 'BANKNIFTY'."""
    parts = trading_symbol.split("-")
    if len(parts) < 3 or parts[-1] != "FUT":
        return None
    return "-".join(parts[:-2])


class ScripMaster:
    """Parsed subset of Dhan's instrument dump, refreshed once per day."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.equities: dict[tuple[str, str], Instrument] = {}
        self.indices: dict[str, Instrument] = {}
        self.options: dict[str, list[Instrument]] = {}
        self.futures: dict[str, list[Instrument]] = {}
        self.by_security_id: dict[tuple[str, str], Instrument] = {}
        self.loaded_for: date | None = None
        self._lock = asyncio.Lock()

    def _cache_path(self, day: date) -> Path:
        return self.cache_dir / f"dhan-scrip-master-{day.isoformat()}.csv"

    async def ensure(self, client: httpx.AsyncClient) -> None:
        today = now_ist().date()
        if self.loaded_for == today:
            return
        async with self._lock:
            if self.loaded_for == today:
                return
            path = self._cache_path(today)
            if not path.exists():
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                log.info("dhan: downloading scrip master to %s", path)
                tmp = path.with_suffix(".part")
                try:
                    async with client.stream("GET", SCRIP_MASTER_URL, timeout=180.0) as resp:
                        resp.raise_for_status()
                        with tmp.open("wb") as fh:
                            async for chunk in resp.aiter_bytes(1 << 16):
                                fh.write(chunk)
                    tmp.replace(path)
                except Exception as exc:  # noqa: BLE001
                    tmp.unlink(missing_ok=True)
                    stale = sorted(self.cache_dir.glob("dhan-scrip-master-*.csv"))
                    if not stale:
                        raise BrokerError(f"could not fetch instrument list: {exc}") from exc
                    path = stale[-1]
                    log.warning("dhan: scrip master download failed (%s), using %s", exc, path)
                # Keep only the newest few dumps.
                for old in sorted(self.cache_dir.glob("dhan-scrip-master-*.csv"))[:-3]:
                    old.unlink(missing_ok=True)

            await asyncio.to_thread(self._parse, path, today)
            self.loaded_for = today
            log.info(
                "dhan: instruments loaded - %d equities, %d indices, %d option underlyings",
                len(self.equities),
                len(self.indices),
                len(self.options),
            )

    def _parse(self, path: Path, today: date) -> None:
        equities: dict[tuple[str, str], Instrument] = {}
        indices: dict[str, Instrument] = {}
        options: dict[str, list[Instrument]] = {}
        futures: dict[str, list[Instrument]] = {}
        by_sid: dict[tuple[str, str], Instrument] = {}

        with path.open("r", newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                exch = _clean(row.get("SEM_EXM_EXCH_ID"))
                seg_code = _clean(row.get("SEM_SEGMENT"))
                inst = _clean(row.get("SEM_INSTRUMENT_NAME"))
                if inst not in WANTED_INSTRUMENTS:
                    continue
                segment = SEGMENT_MAP.get((exch, seg_code))
                if segment is None:
                    continue

                symbol = _clean(row.get("SEM_TRADING_SYMBOL"))
                security_id = _clean(row.get("SEM_SMST_SECURITY_ID"))
                if not symbol or not security_id:
                    continue

                expiry_raw = _clean(row.get("SEM_EXPIRY_DATE"))
                expiry = expiry_raw.split(" ")[0] if expiry_raw else None
                if expiry in {"", "0001-01-01"}:
                    expiry = None

                # Tick size in the dump is in paise; the engine works in rupees.
                tick = _num(row.get("SEM_TICK_SIZE")) / 100.0
                if tick <= 0:
                    tick = 0.05

                lot = int(_num(row.get("SEM_LOT_UNITS"), 1.0) or 1.0)

                instrument = Instrument(
                    security_id=security_id,
                    symbol=symbol,
                    segment=segment,
                    instrument_type=inst,
                    display_name=_clean(row.get("SEM_CUSTOM_SYMBOL")) or symbol,
                    lot_size=max(1, lot),
                    tick_size=tick,
                    expiry=expiry,
                    strike=_num(row.get("SEM_STRIKE_PRICE")) or None,
                    option_type=_clean(row.get("SEM_OPTION_TYPE")) or None,
                )

                if inst == "EQUITY":
                    series = _clean(row.get("SEM_SERIES"))
                    if series not in EQUITY_SERIES:
                        continue
                    key = (exch, symbol.upper())
                    if key not in equities or series == "EQ":
                        equities[key] = instrument
                    by_sid[(segment, security_id)] = instrument
                elif inst == "INDEX":
                    indices[symbol.upper()] = instrument
                    by_sid[(segment, security_id)] = instrument
                elif inst in {"OPTIDX", "OPTSTK"}:
                    if expiry is None or expiry < today.isoformat():
                        continue
                    parsed = _parse_option_symbol(symbol)
                    if parsed is None:
                        continue
                    underlying, opt_type = parsed
                    instrument.underlying = underlying
                    if instrument.option_type not in {"CE", "PE"}:
                        instrument.option_type = opt_type
                    options.setdefault(underlying.upper(), []).append(instrument)
                    by_sid[(segment, security_id)] = instrument
                else:  # FUTIDX / FUTSTK
                    if expiry is None or expiry < today.isoformat():
                        continue
                    underlying = _parse_future_symbol(symbol)
                    if underlying is None:
                        continue
                    instrument.underlying = underlying
                    futures.setdefault(underlying.upper(), []).append(instrument)
                    by_sid[(segment, security_id)] = instrument

        for rows in options.values():
            rows.sort(key=lambda i: (i.expiry or "", i.strike or 0.0, i.option_type or ""))
        for rows in futures.values():
            rows.sort(key=lambda i: i.expiry or "")

        self.equities = equities
        self.indices = indices
        self.options = options
        self.futures = futures
        self.by_security_id = by_sid


class DhanBroker(Broker):
    name = "dhan"
    supports_live_orders = True

    # Index spot security ids live in the INDEX rows of the scrip master; these
    # aliases map the names people actually type to those rows.
    INDEX_ALIASES = {
        "NIFTY": "NIFTY",
        "NIFTY50": "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "NIFTYBANK": "BANKNIFTY",
        "FINNIFTY": "FINNIFTY",
        "MIDCPNIFTY": "MIDCPNIFTY",
        "SENSEX": "SENSEX",
    }

    def __init__(self, *, client_id: str, access_token: str, cache_dir: Path):
        if not client_id or not access_token:
            raise BrokerError(
                "Dhan needs DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in the environment"
            )
        self.client_id = client_id
        self.access_token = access_token
        self.scrips = ScripMaster(cache_dir)
        self._client: httpx.AsyncClient | None = None

        self._order_bucket = TokenBucket(8, burst=8, name="dhan-order")
        self._data_bucket = TokenBucket(4, burst=4, name="dhan-data")
        self._quote_bucket = TokenBucket(0.9, burst=1, name="dhan-quote")
        self._misc_bucket = TokenBucket(10, burst=10, name="dhan-misc")
        self._order_quota = DailyQuota(6500, name="dhan-order-day")
        self._data_quota = DailyQuota(90000, name="dhan-data-day")

        self._candle_cache: dict[tuple[str, str, int], tuple[datetime, CandleSeries]] = {}
        self._history_cache: dict[tuple, CandleSeries] = {}

    # ---- plumbing ----
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=API_BASE,
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "access-token": self.access_token,
                    "client-id": self.client_id,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self, method: str, endpoint: str, *, json: dict | None = None, bucket: str = "misc"
    ) -> dict | list:
        buckets = {
            "order": self._order_bucket,
            "data": self._data_bucket,
            "quote": self._quote_bucket,
            "misc": self._misc_bucket,
        }
        day = now_ist().date().isoformat()
        if bucket == "order" and not self._order_quota.check_and_increment(day):
            raise BrokerError("daily order quota guard tripped", code="LOCAL_QUOTA")
        if bucket == "data" and not self._data_quota.check_and_increment(day):
            raise BrokerError("daily data quota guard tripped", code="LOCAL_QUOTA")
        await buckets[bucket].acquire()

        try:
            resp = await self.client.request(method, endpoint, json=json)
        except httpx.HTTPError as exc:
            raise BrokerError(f"network error calling {endpoint}: {exc}", retryable=True) from exc

        if resp.status_code == 429:
            raise BrokerError("rate limited by Dhan", code="DH-904", retryable=True)

        try:
            payload = resp.json() if resp.content else {}
        except ValueError:
            payload = {}

        if resp.status_code >= 300:
            code = ""
            message = resp.text[:300]
            if isinstance(payload, dict):
                code = str(payload.get("errorCode") or payload.get("error_code") or "")
                message = str(
                    payload.get("errorMessage") or payload.get("error_message") or message
                )
                # Data-API errors arrive as {"data": {"806": "..."}, "status": "failed"}
                nested = payload.get("data")
                if not code and isinstance(nested, dict) and nested:
                    code = str(next(iter(nested)))
                    message = str(next(iter(nested.values())))

            if code in DATA_SUBSCRIPTION_CODES or "not Subscribed" in message:
                raise BrokerError(
                    "Dhan Data APIs are not subscribed on this account, so candles and "
                    "quotes cannot be fetched. Trading APIs are free but market data is a "
                    "paid add-on: subscribe under DhanHQ Trading APIs on web.dhan.co. "
                    f"(endpoint {endpoint}, code {code})",
                    code=code or "806",
                )
            if code in TOKEN_CODES:
                raise BrokerError(
                    "Dhan rejected the access token as invalid or expired. Tokens last 24 "
                    "hours - generate a fresh one on web.dhan.co and save it in the Setup "
                    f"tab. (endpoint {endpoint}, code {code})",
                    code=code,
                )

            retryable = code in {"DH-904", "DH-908", "DH-909", "805", "800"}
            raise BrokerError(
                f"Dhan {endpoint} failed ({resp.status_code} {code}): {message}",
                code=code,
                retryable=retryable,
            )

        if isinstance(payload, dict) and payload.get("status") == "failed":
            raise BrokerError(f"Dhan {endpoint} reported failure: {payload}")
        return payload

    async def health(self) -> dict:
        data = await self._request("GET", "/profile")
        if not isinstance(data, dict):
            raise BrokerError("unexpected /profile response")
        return {
            "broker": self.name,
            "client_id": data.get("dhanClientId"),
            "token_validity": data.get("tokenValidity"),
            "active_segments": data.get("activeSegment"),
            "data_plan": data.get("dataPlan"),
            "data_validity": data.get("dataValidity"),
        }

    # ---- instruments ----
    async def resolve_equity(self, symbol: str, exchange: str = "NSE") -> Instrument:
        await self.scrips.ensure(self.client)
        key = (exchange.upper(), symbol.upper())
        inst = self.scrips.equities.get(key)
        if inst is None:
            raise BrokerError(f"{symbol} not found as an {exchange} cash-segment instrument")
        return inst

    async def index_instrument(self, underlying: str) -> Instrument | None:
        await self.scrips.ensure(self.client)
        name = self.INDEX_ALIASES.get(underlying.upper(), underlying.upper())
        return self.scrips.indices.get(name)

    async def option_chain_instruments(
        self, underlying: str, expiry: str | None = None
    ) -> list[Instrument]:
        await self.scrips.ensure(self.client)
        rows = self.scrips.options.get(underlying.upper(), [])
        if not rows:
            raise BrokerError(f"no live option contracts found for {underlying}")
        if expiry:
            rows = [r for r in rows if r.expiry == expiry]
            if not rows:
                raise BrokerError(f"no {underlying} contracts expiring on {expiry}")
        return rows

    async def expiries(self, underlying: str) -> list[str]:
        await self.scrips.ensure(self.client)
        rows = self.scrips.options.get(underlying.upper(), [])
        return sorted({r.expiry for r in rows if r.expiry})

    async def instrument_by_security_id(self, segment: str, security_id: str) -> Instrument | None:
        await self.scrips.ensure(self.client)
        return self.scrips.by_security_id.get((segment, str(security_id)))

    # ---- market data ----
    async def intraday_candles(
        self, instrument: Instrument, day: date, interval_minutes: int = 1
    ) -> CandleSeries:
        """1-minute candles covering enough prior sessions to warm the indicators up."""
        cache_key = (instrument.segment, instrument.security_id, interval_minutes)
        now = now_ist()
        cached = self._candle_cache.get(cache_key)
        # A 1-minute candle cannot change once its minute has passed, so caching
        # for 45 seconds keeps us well inside the data rate limit.
        if cached and (now - cached[0]).total_seconds() < 45:
            return cached[1]

        start_day = previous_trading_day(day, 5)
        from_dt = session_open(instrument.segment, start_day)
        to_dt = min(now, session_close(instrument.segment, day))
        if to_dt <= from_dt:
            to_dt = session_close(instrument.segment, day)

        wants_oi = instrument.segment in {"NSE_FNO", "BSE_FNO", "MCX_COMM"}
        payload = {
            "securityId": instrument.security_id,
            "exchangeSegment": instrument.segment,
            "instrument": instrument.instrument_type,
            "interval": str(interval_minutes),
            "oi": wants_oi,
            "fromDate": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": to_dt.strftime("%Y-%m-%d %H:%M:%S"),
        }
        data = await self._request("POST", "/charts/intraday", json=payload, bucket="data")
        if not isinstance(data, dict):
            raise BrokerError("unexpected /charts/intraday response")

        series = build_candles(
            timestamps=data.get("timestamp") or [],
            open_=data.get("open") or [],
            high=data.get("high") or [],
            low=data.get("low") or [],
            close=data.get("close") or [],
            volume=data.get("volume") or [],
            segment=instrument.segment,
            open_interest=data.get("open_interest") or [],
        )
        self._candle_cache[cache_key] = (now, series)
        return series

    async def history_candles(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        """Completed sessions from the Data APIs (paid add-on, like intraday_candles).

        Daily candles come from /charts/historical. Intraday history comes from
        /charts/intraday in pieces of at most 90 days; Dhan offers 1, 5, 15, 25 and
        60-minute candles, so a 30-minute request is served as 15-minute candles, which
        the caller resamples.
        """
        if end < start:
            return CandleSeries([])
        # Completed sessions never change, so one fetch serves the whole run; without
        # this a long-timeframe watch would spend the data quota on every poll.
        cache_key = (instrument.segment, instrument.security_id, int(interval_minutes),
                     start.isoformat(), end.isoformat())
        hit = self._history_cache.get(cache_key)
        if hit is not None:
            return hit
        series = await self._fetch_history(instrument, interval_minutes, start, end)
        self._history_cache[cache_key] = series
        if len(self._history_cache) > 256:
            self._history_cache.pop(next(iter(self._history_cache)))
        return series

    async def _fetch_history(
        self, instrument: Instrument, interval_minutes: int, start: date, end: date
    ) -> CandleSeries:
        wants_oi = instrument.segment in {"NSE_FNO", "BSE_FNO", "MCX_COMM"}
        base = {
            "securityId": instrument.security_id,
            "exchangeSegment": instrument.segment,
            "instrument": instrument.instrument_type,
            "oi": wants_oi,
        }
        if interval_minutes >= 1440:
            payload = {
                **base,
                "expiryCode": 0,
                "fromDate": start.isoformat(),
                # toDate is exclusive on this endpoint.
                "toDate": (end + timedelta(days=1)).isoformat(),
            }
            data = await self._request("POST", "/charts/historical", json=payload, bucket="data")
            if not isinstance(data, dict):
                raise BrokerError("unexpected /charts/historical response")
            rows: list[Candle] = []
            stamps = data.get("timestamp") or []
            cols = [data.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
            ois = data.get("open_interest") or []
            for i, epoch in enumerate(stamps):
                try:
                    day = datetime.fromtimestamp(float(epoch), IST).date()
                    rows.append(Candle(
                        ts=session_open(instrument.segment, day),
                        open=float(cols[0][i]), high=float(cols[1][i]), low=float(cols[2][i]),
                        close=float(cols[3][i]),
                        volume=float(cols[4][i]) if i < len(cols[4]) else 0.0,
                        oi=float(ois[i]) if i < len(ois) else 0.0,
                    ))
                except (IndexError, TypeError, ValueError):
                    continue
            rows.sort(key=lambda c: c.ts)
            return CandleSeries(rows)

        supported = (60, 25, 15, 5, 1)
        interval = next((s for s in supported if interval_minutes % s == 0), 1)
        out: list[Candle] = []
        cur = start
        while cur <= end:
            piece_end = min(end, cur + timedelta(days=85))
            payload = {
                **base,
                "interval": str(interval),
                "fromDate": session_open(instrument.segment, cur).strftime("%Y-%m-%d %H:%M:%S"),
                "toDate": session_close(instrument.segment, piece_end).strftime("%Y-%m-%d %H:%M:%S"),
            }
            data = await self._request("POST", "/charts/intraday", json=payload, bucket="data")
            if isinstance(data, dict):
                out.extend(build_candles(
                    timestamps=data.get("timestamp") or [],
                    open_=data.get("open") or [],
                    high=data.get("high") or [],
                    low=data.get("low") or [],
                    close=data.get("close") or [],
                    volume=data.get("volume") or [],
                    segment=instrument.segment,
                    open_interest=data.get("open_interest") or [],
                ).candles)
            cur = piece_end + timedelta(days=1)
        out.sort(key=lambda c: c.ts)
        return CandleSeries(out)

    async def ltp(self, instruments: list[Instrument]) -> dict[str, float]:
        if not instruments:
            return {}
        by_segment: dict[str, list[int]] = {}
        for inst in instruments:
            try:
                sid = int(inst.security_id)
            except (TypeError, ValueError):
                continue
            by_segment.setdefault(inst.segment, []).append(sid)

        out: dict[str, float] = {}
        # The quote endpoint takes up to 1000 instruments but only 1 request/sec,
        # so everything is batched into a single call.
        data = await self._request("POST", "/marketfeed/ltp", json=by_segment, bucket="quote")
        if not isinstance(data, dict):
            return out
        for _segment, entries in (data.get("data") or {}).items():
            if not isinstance(entries, dict):
                continue
            for sid, payload in entries.items():
                if isinstance(payload, dict) and payload.get("last_price") is not None:
                    try:
                        out[str(sid)] = float(payload["last_price"])
                    except (TypeError, ValueError):
                        continue
        return out

    # ---- trading ----
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
        payload = {
            "dhanClientId": self.client_id,
            "transactionType": side.value,
            "exchangeSegment": instrument.segment,
            "productType": self.product_code(product_type, instrument.segment),
            "orderType": order_type.value,
            "validity": "DAY",
            "securityId": instrument.security_id,
            "quantity": int(quantity),
            "disclosedQuantity": 0,
            "price": round(float(price), 2) if order_type in {OrderType.LIMIT, OrderType.STOP_LOSS} else 0,
            "triggerPrice": round(float(trigger_price), 2)
            if order_type in {OrderType.STOP_LOSS, OrderType.STOP_LOSS_MARKET}
            else 0,
            "afterMarketOrder": False,
        }
        if correlation_id:
            payload["correlationId"] = correlation_id[:30]

        data = await self._request("POST", "/orders", json=payload, bucket="order")
        if not isinstance(data, dict) or not data.get("orderId"):
            raise BrokerError(f"order placement returned no orderId: {data}")
        status = STATUS_MAP.get(str(data.get("orderStatus", "")).upper(), OrderStatus.PENDING)
        return PlacedOrder(
            broker_order_id=str(data["orderId"]),
            status=status,
            message=str(data.get("orderStatus", "")),
        )

    CASH_SEGMENTS = {"NSE_EQ", "BSE_EQ"}

    @classmethod
    def product_code(cls, product: str, segment: str) -> str:
        """The engine's INTRADAY / DELIVERY as Dhan's productType.

        Delivery is CNC for shares and MARGIN (NRML, carried forward) for futures and
        options. Dhan's own codes pass through unchanged.
        """
        p = (product or "INTRADAY").upper()
        if p == "DELIVERY":
            return "CNC" if segment in cls.CASH_SEGMENTS else "MARGIN"
        return p

    async def order_state(self, broker_order_id: str) -> OrderState:
        data = await self._request("GET", f"/orders/{broker_order_id}")
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            raise BrokerError("unexpected order status response")
        status = STATUS_MAP.get(str(data.get("orderStatus", "")).upper(), OrderStatus.UNKNOWN)
        return OrderState(
            broker_order_id=str(data.get("orderId") or broker_order_id),
            status=status,
            filled_quantity=int(data.get("filledQty") or 0),
            average_price=float(data.get("averageTradedPrice") or 0.0),
            message=str(data.get("omsErrorDescription") or data.get("orderStatus") or ""),
        )

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            await self._request("DELETE", f"/orders/{broker_order_id}", bucket="order")
            return True
        except BrokerError as exc:
            log.warning("dhan: cancel of %s failed: %s", broker_order_id, exc)
            return False

    async def positions(self) -> list[BrokerPosition]:
        data = await self._request("GET", "/positions")
        rows = data if isinstance(data, list) else []
        out: list[BrokerPosition] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                BrokerPosition(
                    security_id=str(row.get("securityId") or ""),
                    segment=str(row.get("exchangeSegment") or ""),
                    quantity=int(row.get("netQty") or 0),
                    # A short was opened by selling, so its entry is the sell average;
                    # reading buyAvg would adopt a short at the wrong price on restart.
                    average_price=float(
                        (row.get("sellAvg") if int(row.get("netQty") or 0) < 0
                         else row.get("buyAvg")) or 0.0
                    ),
                    symbol=str(row.get("tradingSymbol") or ""),
                )
            )
        return out

    async def holdings(self) -> list[BrokerPosition]:
        """Settled delivery shares. Dhan answers an empty account with an error, which
        is read as no holdings."""
        try:
            data = await self._request("GET", "/holdings")
        except BrokerError as exc:
            if "no holdings" in str(exc).lower():
                return []
            raise
        rows = data if isinstance(data, list) else []
        out: list[BrokerPosition] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            qty = int(row.get("totalQty") or row.get("availableQty") or 0)
            if qty <= 0:
                continue
            exchange = str(row.get("exchange") or "NSE").upper()
            out.append(BrokerPosition(
                security_id=str(row.get("securityId") or ""),
                segment="BSE_EQ" if exchange.startswith("BSE") else "NSE_EQ",
                quantity=qty,
                average_price=float(row.get("avgCostPrice") or 0.0),
                symbol=str(row.get("tradingSymbol") or ""),
            ))
        return out
