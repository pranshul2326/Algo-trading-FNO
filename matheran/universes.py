"""Scanner universes: index constituent lists, and parsing of custom symbols.

The eight index lists come from fixed, allowlisted URLs only (never from user
input): NSE's archive host first, then niftyindices.com, the official publisher,
which wants a browser-like User-Agent. Each list is fetched at most once per IST
day and kept under cache/universes/; when every source fails, the cached copy of any
age is used, and failing that the dated snapshot shipped in universe_snapshot/.

The F&O and MCX universes are derived from the Upstox instrument masters by the
scanner; this module only remembers their sizes for display (note_derived).

No I/O happens at import time and no broker module is imported, so config
validation can use UNIVERSE_IDS and parse_symbol without touching the network.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from .timeutil import now_ist

log = logging.getLogger(__name__)

INDEX_UNIVERSES = {            # id: (label, file, nominal size)
    "nifty50":     ("Nifty 50",           "ind_nifty50list.csv",          50),
    "niftynext50": ("Nifty Next 50",      "ind_niftynext50list.csv",      50),
    "nifty200":    ("Nifty 200",          "ind_nifty200list.csv",        200),
    "nifty500":    ("Nifty 500",          "ind_nifty500list.csv",        500),
    "midcap150":   ("Nifty Midcap 150",   "ind_niftymidcap150list.csv",  150),
    "midcap100":   ("Nifty Midcap 100",   "ind_niftymidcap100list.csv",  100),
    "smallcap250": ("Nifty Smallcap 250", "ind_niftysmallcap250list.csv", 250),
    "smallcap100": ("Nifty Smallcap 100", "ind_niftysmallcap100list.csv", 100),
}
DERIVED_UNIVERSES = {
    "fno": ("F&O stocks (NSE stock futures)", 220),
    "mcx": ("MCX commodities (near month)", 30),
}
UNIVERSE_IDS = ("nifty50", "niftynext50", "fno", "nifty200", "nifty500",
                "midcap150", "midcap100", "smallcap250", "smallcap100", "mcx")   # display order
DERIVED_SOURCE = "Upstox instrument master"

# The Upstox adapter's User-Agent, as a literal (no broker import).
APP_HEADERS = {"User-Agent": "matheran/0.1 (+https://localhost) python-httpx",
               "Accept": "text/csv,*/*"}
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                   "Accept": "text/csv,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9"}
SOURCES = (("archives.nseindia.com", "https://archives.nseindia.com/content/indices/", APP_HEADERS),
           ("niftyindices.com", "https://www.niftyindices.com/IndexConstituent/", BROWSER_HEADERS))
SNAPSHOT_DIR = Path(__file__).parent / "universe_snapshot"
MAX_CSV_BYTES = 512 * 1024
FETCH_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

MAX_CUSTOM = 200
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-_.]{0,29}$")
EXCHANGES = ("NSE", "BSE", "MCX")
CSV_COLUMNS = ("Company Name", "Industry", "Symbol", "Series", "ISIN Code")
ISIN_RE = re.compile(r"^IN[A-Z0-9]{9}[0-9]$")
CSV_SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
NAME_MAX = 100


class UniverseUnavailable(RuntimeError):
    """No live list, no cache and no usable snapshot (the API answers 502)."""


@dataclass(frozen=True, slots=True)
class Member:
    symbol: str
    isin: str
    name: str
    series: str


@dataclass(slots=True)
class IndexList:
    id: str
    label: str
    members: list[Member]
    skipped: list[tuple[str, str]]   # (symbol, reason)
    source: str                      # "archives.nseindia.com" | "niftyindices.com" | "cache" | "snapshot"
    as_of: date                      # fetch date (live or cache) or snapshot date


# ------------------------------------------------------------------ parsing
def clean_text(value, limit: int = NAME_MAX) -> str:
    """Display text from an external source: control and format characters removed,
    whitespace collapsed, at most `limit` characters."""
    text = "".join(ch for ch in str(value or "") if not unicodedata.category(ch).startswith("C"))
    return " ".join(text.split())[:limit]


def parse_symbol(text) -> tuple[str, str]:
    """ "bse:reliance" -> ("BSE", "RELIANCE"); a bare symbol is NSE."""
    error = ValueError(f"custom symbol {text!r}: use NSE:SYMBOL, BSE:SYMBOL or MCX:COMMODITY")
    if not isinstance(text, str):
        raise error
    raw = text.strip().upper()
    exchange, sep, symbol = raw.partition(":")
    if not sep:
        exchange, symbol = "NSE", raw
    exchange, symbol = exchange.strip(), symbol.strip()
    if exchange not in EXCHANGES or not SYMBOL_RE.match(symbol):
        raise error
    return exchange, symbol


def parse_csv(text: str, nominal: int) -> tuple[list[Member], list[tuple[str, str]]]:
    """Members and skipped rows of one index CSV (already decoded with utf-8-sig).
    ValueError when a column is missing or the tradable count is implausible, which
    means "this source failed, try the next one"."""
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text))
    columns = {(c or "").strip(): c for c in (reader.fieldnames or [])}
    missing = [c for c in CSV_COLUMNS if c not in columns]
    if missing:
        raise ValueError(f"index CSV is missing column(s): {', '.join(missing)}")
    members: list[Member] = []
    skipped: list[tuple[str, str]] = []
    for row in reader:
        get = lambda col: str(row.get(columns[col]) or "").strip()  # noqa: E731
        symbol, isin = get("Symbol"), get("ISIN Code")
        if not ISIN_RE.match(isin):
            skipped.append((clean_text(symbol, 30), "placeholder, not tradable"))
            continue
        if not CSV_SYMBOL_RE.match(symbol):
            skipped.append((clean_text(symbol, 30), "invalid symbol"))
            continue
        clean_text(get("Industry"))   # not kept; validated the same way as the name
        members.append(Member(symbol=symbol, isin=isin, name=clean_text(get("Company Name")),
                              series=clean_text(get("Series"), 10)))
    low, high = math.floor(0.9 * nominal), nominal + 5
    if not low <= len(members) <= high:
        raise ValueError(
            f"index CSV has {len(members)} tradable rows, expected {low}-{high}"
        )
    return members, skipped


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _data_rows(text: str) -> int:
    if text.startswith("\ufeff"):
        text = text[1:]
    return sum(1 for _ in csv.DictReader(io.StringIO(text)))


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# -------------------------------------------------------------------- store
class UniverseStore:
    """Index lists with their source and date. `cache_dir` is the app's cache
    directory; the lists live in its universes/ subdirectory."""

    def __init__(self, cache_dir: Path, snapshot_dir: Path = SNAPSHOT_DIR):
        self.dir = Path(cache_dir) / "universes"
        self.snapshot_dir = Path(snapshot_dir)
        self._locks: dict[str, asyncio.Lock] = {}
        self._loaded: dict[str, IndexList] = {}
        self._derived: dict[str, tuple[int, date]] = {}
        self._warned: set[tuple[str, date]] = set()

    # ---- files (blocking: called through asyncio.to_thread) ----
    def _csv_path(self, file: str) -> Path:
        return self.dir / file

    def _meta_path(self, file: str) -> Path:
        return self.dir / f"{file}.meta.json"

    def _read_meta(self, file: str) -> dict | None:
        try:
            meta = json.loads(self._meta_path(file).read_text())
        except (OSError, ValueError):
            return None
        return meta if isinstance(meta, dict) else None

    def _read_cache(self, file: str) -> tuple[str, dict | None] | None:
        try:
            data = self._csv_path(file).read_bytes()
        except OSError:
            return None
        try:
            return data.decode("utf-8-sig"), self._read_meta(file)
        except UnicodeDecodeError:
            return None

    def _write_cache(self, file: str, data: bytes, meta: dict) -> None:
        _write_atomic(self._csv_path(file), data)
        _write_atomic(self._meta_path(file), json.dumps(meta, indent=1).encode())

    def _manifest(self) -> dict | None:
        try:
            manifest = json.loads((self.snapshot_dir / "manifest.json").read_text())
        except (OSError, ValueError):
            return None
        return manifest if isinstance(manifest, dict) else None

    def _read_snapshot(self, file: str) -> tuple[str, date]:
        manifest = self._manifest()
        entry = ((manifest or {}).get("files") or {}).get(file)
        if not isinstance(entry, dict):
            raise ValueError("not in the snapshot manifest")
        data = (self.snapshot_dir / file).read_bytes()
        if _sha256(data) != entry.get("sha256"):
            raise ValueError("snapshot checksum mismatch")
        return data.decode("utf-8-sig"), date.fromisoformat(str(manifest["date"]))

    # ---- network ----
    async def _fetch(self, base: str, headers: dict, file: str) -> bytes:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT, follow_redirects=False, headers=headers
        ) as client:
            async with client.stream("GET", base + file) as resp:
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_CSV_BYTES:
                        raise ValueError("response larger than 512 KB")
        return bytes(buf)

    # ---- public ----
    async def index_list(self, uid: str) -> IndexList:
        if uid not in INDEX_UNIVERSES:
            raise ValueError(f"unknown index universe {uid!r}")
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            found = await self._index_list(uid)
            self._loaded[uid] = found
            return found

    async def _index_list(self, uid: str) -> IndexList:
        label, file, nominal = INDEX_UNIVERSES[uid]
        today = now_ist().date()

        cached = await asyncio.to_thread(self._read_cache, file)
        if cached is not None:
            text, meta = cached
            if meta and meta.get("date") == today.isoformat():
                try:
                    members, skipped = parse_csv(text, nominal)
                    host = str(meta.get("host") or "cache")
                    return IndexList(uid, label, members, skipped, host, today)
                except ValueError:
                    pass   # a damaged copy: fetch again

        first_error = ""
        for host, base, headers in SOURCES:
            try:
                data = await self._fetch(base, headers, file)
                text = data.decode("utf-8-sig")
                members, skipped = parse_csv(text, nominal)
            except (httpx.HTTPError, ValueError, UnicodeDecodeError) as exc:
                detail = f"{host}: {str(exc) or type(exc).__name__}"
                first_error = first_error or detail
                log.debug("universes: %s %s failed (%s)", label, host, detail)
                continue
            meta = {"date": today.isoformat(), "fetched_at": now_ist().isoformat(timespec="seconds"),
                    "source": base + file, "host": host, "rows": _data_rows(text),
                    "tradable": len(members), "sha256": _sha256(data)}
            try:
                await asyncio.to_thread(self._write_cache, file, data, meta)
            except OSError as exc:
                log.warning("universes: could not cache %s (%s)", label, exc)
            return IndexList(uid, label, members, skipped, host, today)

        if cached is not None:
            text, meta = cached
            try:
                members, skipped = parse_csv(text, nominal)
            except ValueError:
                pass
            else:
                as_of = today
                try:
                    as_of = date.fromisoformat(str((meta or {}).get("date")))
                except ValueError:
                    pass
                self._warn(uid, today, f"{label} list from the cache of {as_of}", first_error)
                return IndexList(uid, label, members, skipped, "cache", as_of)

        try:
            text, as_of = await asyncio.to_thread(self._read_snapshot, file)
            members, skipped = parse_csv(text, nominal)
        except (OSError, ValueError, KeyError, UnicodeDecodeError) as exc:
            log.error("universes: %s snapshot unusable (%s)", label, exc)
            raise UniverseUnavailable(
                f"{label}: no live list, no cache, and the shipped snapshot is missing or corrupted"
            ) from exc
        self._warn(uid, today, f"{label} list from the shipped snapshot of {as_of}", first_error)
        return IndexList(uid, label, members, skipped, "snapshot", as_of)

    def _warn(self, uid: str, today: date, fallback: str, error: str) -> None:
        if (uid, today) in self._warned:
            return
        self._warned.add((uid, today))
        log.warning("universes: %s: live fetch failed (%s)", fallback, error or "unknown error")

    def note_derived(self, uid: str, size: int, as_of: date) -> None:
        """Remember the size of a derived universe (F&O, MCX) once it is known."""
        if uid in DERIVED_UNIVERSES:
            self._derived[uid] = (int(size), as_of)

    def info(self) -> list[dict]:
        """Every universe with its size, source and date, without any network call.
        Reads files: callers on the event loop use asyncio.to_thread(store.info)."""
        today = now_ist().date()
        manifest = self._manifest() or {}
        files = manifest.get("files") or {}
        out: list[dict] = []
        for uid in UNIVERSE_IDS:
            if uid in DERIVED_UNIVERSES:
                label, nominal = DERIVED_UNIVERSES[uid]
                size, as_of = self._derived.get(uid, (None, None))
                out.append({"id": uid, "label": label, "nominal": nominal, "size": size,
                            "source": DERIVED_SOURCE if size is not None else None,
                            "as_of": as_of.isoformat() if as_of else None,
                            "loaded": uid in self._derived})
                continue
            label, file, nominal = INDEX_UNIVERSES[uid]
            loaded = self._loaded.get(uid)
            if loaded is not None:
                size, source, as_of = len(loaded.members), loaded.source, loaded.as_of.isoformat()
            else:
                meta = self._read_meta(file)
                snap = files.get(file) if isinstance(files, dict) else None
                if meta and isinstance(meta.get("tradable"), int):
                    size = meta["tradable"]
                    as_of = str(meta.get("date") or "") or None
                    source = str(meta.get("host") or "cache") if as_of == today.isoformat() else "cache"
                elif isinstance(snap, dict):
                    size, source, as_of = snap.get("tradable"), "snapshot", manifest.get("date")
                else:
                    size, source, as_of = None, None, None
            out.append({"id": uid, "label": label, "nominal": nominal, "size": size,
                        "source": source, "as_of": as_of, "loaded": loaded is not None})
        return out
