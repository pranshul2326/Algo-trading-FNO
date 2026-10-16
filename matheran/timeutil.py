"""IST time helpers. Every timestamp inside the engine is timezone-aware IST."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Session start per exchange segment. Candle buckets are anchored to these so a
# 3-minute candle spans 09:15-09:18 rather than 09:14-09:17.
SESSION_OPEN = {
    "NSE_EQ": time(9, 15),
    "BSE_EQ": time(9, 15),
    "NSE_FNO": time(9, 15),
    "BSE_FNO": time(9, 15),
    "NSE_CURRENCY": time(9, 0),
    "BSE_CURRENCY": time(9, 0),
    "MCX_COMM": time(9, 0),
    "IDX_I": time(9, 15),
}
SESSION_CLOSE = {
    "NSE_EQ": time(15, 30),
    "BSE_EQ": time(15, 30),
    "NSE_FNO": time(15, 30),
    "BSE_FNO": time(15, 30),
    "NSE_CURRENCY": time(17, 0),
    "BSE_CURRENCY": time(17, 0),
    "MCX_COMM": time(23, 30),
    "IDX_I": time(15, 30),
}


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def session_open(segment: str, day: date) -> datetime:
    t = SESSION_OPEN.get(segment, time(9, 15))
    return datetime.combine(day, t, tzinfo=IST)


def session_close(segment: str, day: date) -> datetime:
    t = SESSION_CLOSE.get(segment, time(15, 30))
    return datetime.combine(day, t, tzinfo=IST)


_NEW_YORK = ZoneInfo("America/New_York")


def mcx_close_time(day: date) -> time:
    """MCX's close for internationally linked contracts: 23:30 IST while US daylight
    saving is in effect (judged at noon New York time on `day`), else 23:55. Only a
    fallback; SESSION_CLOSE["MCX_COMM"] stays 23:30 and agri contracts close earlier."""
    noon = datetime.combine(day, time(12, 0), tzinfo=_NEW_YORK)
    return time(23, 30) if noon.dst() else time(23, 55)


def parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")[:2]
    return time(int(hh), int(mm))


def at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, parse_hhmm(hhmm), tzinfo=IST)


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def previous_trading_day(day: date, back: int = 1) -> date:
    """Walk back `back` weekdays. Exchange holidays are not modelled; the engine
    only uses this to widen a historical-data window, so overshooting is harmless."""
    d = day
    remaining = back
    while remaining > 0:
        d -= timedelta(days=1)
        if not is_weekend(d):
            remaining -= 1
    return d


def fmt(dt: datetime) -> str:
    return to_ist(dt).strftime("%Y-%m-%d %H:%M:%S")
