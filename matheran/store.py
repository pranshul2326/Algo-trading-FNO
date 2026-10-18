"""Durable state: watch definitions and a trade log on local disk.

Intentionally boring. Atomic writes via temp-file rename so a crash mid-write
cannot leave a half-written state file behind.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .candles import normalize_candle_type
from .models import (
    EXIT_MODES,
    Direction,
    Instrument,
    OrderRef,
    OrderStatus,
    OrderType,
    Position,
    Side,
    Trade,
    TradeTicket,
    Watch,
    WatchState,
    exit_mode_of,
    product_of,
)
from .timeutil import IST, to_ist

log = logging.getLogger(__name__)


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return to_ist(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def _sides(value: Any) -> str:
    text = str(value or "LONG").upper()
    return text if text in {"LONG", "SHORT", "BOTH"} else "LONG"


def _workspace(value: Any) -> str:
    """A stored workspace id, or "" for a record from before workspaces (or one that
    names something unknown, which then falls back to the legacy rule)."""
    from .workspaces import WORKSPACES

    text = str(value or "").strip()
    return text if text in WORKSPACES else ""


def _level(value: Any) -> float | None:
    """A stored price level: a positive number, else None (not set)."""
    try:
        level = float(value)
    except (TypeError, ValueError):
        return None
    return level if level > 0 else None


def _instrument(data: dict) -> Instrument:
    fields = {f for f in Instrument.__dataclass_fields__}
    return Instrument(**{k: v for k, v in data.items() if k in fields})


def _order_ref(data: dict | None) -> OrderRef | None:
    if not data:
        return None
    return OrderRef(
        broker_order_id=str(data.get("broker_order_id", "")),
        correlation_id=str(data.get("correlation_id", "")),
        side=Side(data.get("side", "BUY")),
        order_type=OrderType(data.get("order_type", "MARKET")),
        quantity=int(data.get("quantity", 0)),
        price=float(data.get("price", 0.0)),
        trigger_price=float(data.get("trigger_price", 0.0)),
        status=OrderStatus(data.get("status", "UNKNOWN")),
        filled_quantity=int(data.get("filled_quantity", 0)),
        average_price=float(data.get("average_price", 0.0)),
        message=str(data.get("message", "")),
        placed_at=_dt(data.get("placed_at")) or datetime.now(IST),
    )


def _position(data: dict | None) -> Position | None:
    if not data:
        return None
    entry_time = _dt(data.get("entry_time"))
    return Position(
        instrument=_instrument(data.get("instrument") or {}),
        quantity=int(data.get("quantity", 0)),
        direction=Direction(str(data.get("direction", "LONG")).upper()),
        entry_price=float(data.get("entry_price", 0.0)),
        entry_time=entry_time or datetime.now(IST),
        stop_price=float(data.get("stop_price", 0.0)),
        target_price=data.get("target_price"),
        entry_order_id=data.get("entry_order_id"),
        stop_order_id=data.get("stop_order_id"),
        trail_unit=data.get("trail_unit"),
        trail_value=_opt_float(data.get("trail_value")),
        trail_trigger_pct=_opt_float(data.get("trail_trigger_pct")),
        best_price=_opt_float(data.get("best_price")),
        trailed=bool(data.get("trailed", False)),
        broker_stop_price=_opt_float(data.get("broker_stop_price")),
        # Records from before exit modes said only whether the exit rules applied.
        exit_mode=exit_mode_of(data.get("exit_mode"), data.get("use_exit_rules", True)),
        exit_timeframe=int(data["exit_timeframe"]) if data.get("exit_timeframe") else None,
        product=product_of(data.get("product")),
    )


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticket(data: dict | None) -> TradeTicket | None:
    if not data:
        return None
    try:
        return TradeTicket.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        log.error("store: dropping unreadable order ticket: %s", exc)
        return None


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.watches_path = self.data_dir / "watches.json"
        self.trades_path = self.data_dir / "trades.jsonl"
        self.baskets_path = self.data_dir / "baskets.json"

    # ---- low level ----
    def _write_atomic(self, path: Path, text: str) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.data_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ---- watches ----
    def save_watches(self, watches: list[Watch]) -> None:
        payload = {
            "saved_at": datetime.now(IST).isoformat(),
            "watches": [w.as_dict() for w in watches],
        }
        try:
            self._write_atomic(self.watches_path, json.dumps(payload, indent=2, default=str))
        except OSError as exc:
            log.error("store: could not save watches: %s", exc)

    def load_watches(self) -> list[Watch]:
        if not self.watches_path.exists():
            return []
        try:
            payload = json.loads(self.watches_path.read_text())
        except (OSError, ValueError) as exc:
            log.error("store: watches file unreadable (%s), starting empty", exc)
            return []

        out: list[Watch] = []
        for data in payload.get("watches", []):
            try:
                watch = Watch(
                    id=str(data["id"]),
                    instrument=_instrument(data["instrument"]),
                    quantity=int(data["quantity"]),
                    timeframe_minutes=int(data.get("timeframe_minutes", 5)),
                    stop_loss_pct=float(data.get("stop_loss_pct", 3.0)),
                    target_pct=data.get("target_pct"),
                    kind=str(data.get("kind", "equity")),
                    direction=Direction(str(data.get("direction", "LONG")).upper()),
                    # Records from before BOTH existed only ever traded their direction.
                    sides=_sides(data.get("sides") or data.get("direction")),
                    candle_type=normalize_candle_type(data.get("candle_type")),
                    manual_only=bool(data.get("manual_only", False)),
                    require_adx=bool(data.get("require_adx", False)),
                    adx_min=data.get("adx_min"),
                    state=WatchState(data.get("state", "watching")),
                    created_at=_dt(data.get("created_at")) or datetime.now(IST),
                    updated_at=_dt(data.get("updated_at")) or datetime.now(IST),
                    approval_id=data.get("approval_id"),
                    entry_order=_order_ref(data.get("entry_order")),
                    exit_order=_order_ref(data.get("exit_order")),
                    position=_position(data.get("position")),
                    trades_today=int(data.get("trades_today", 0)),
                    cooldown_until=_dt(data.get("cooldown_until")),
                    notes=str(data.get("notes", "")),
                    basket_id=data.get("basket_id"),
                    ticket=_ticket(data.get("ticket")),
                    chart_symbol=str(data.get("chart_symbol") or ""),
                    product=product_of(data.get("product")),
                    exit_mode=(str(data.get("exit_mode") or "").lower()
                               if str(data.get("exit_mode") or "").lower() in EXIT_MODES else ""),
                    signal_side=str(data.get("signal_side") or ""),
                    signal_at=_dt(data.get("signal_at")),
                    # Absent on records from before workspaces; read as "" (legacy
                    # rule), never filled in here.
                    workspace=_workspace(data.get("workspace")),
                    # Absent on older records: their stop and target are the % above.
                    stop_loss_price=_level(data.get("stop_loss_price")),
                    target_price=_level(data.get("target_price")),
                )
                if watch.state is WatchState.GTT_PENDING and watch.ticket is None:
                    # A GTT with no readable ticket has nothing left to trigger.
                    watch.state = WatchState.WATCHING
                out.append(watch)
            except (KeyError, TypeError, ValueError) as exc:
                log.error("store: skipping malformed watch record: %s", exc)
        return out

    # ---- baskets ----
    def save_baskets(self, rows: list[dict]) -> None:
        try:
            self._write_atomic(
                self.baskets_path,
                json.dumps({"saved_at": datetime.now(IST).isoformat(), "baskets": rows},
                           indent=2, default=str),
            )
        except OSError as exc:
            log.error("store: could not save baskets: %s", exc)

    def load_baskets(self) -> list[dict]:
        if not self.baskets_path.exists():
            return []
        try:
            return json.loads(self.baskets_path.read_text()).get("baskets", [])
        except (OSError, ValueError) as exc:
            log.error("store: baskets file unreadable (%s), starting empty", exc)
            return []

    # ---- trades ----
    def append_trade(self, trade: Trade) -> None:
        try:
            with self.trades_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(trade.as_dict(), default=str) + "\n")
        except OSError as exc:
            log.error("store: could not append trade: %s", exc)

    def load_trades(self, limit: int | None = None) -> list[dict]:
        if not self.trades_path.exists():
            return []
        rows: list[dict] = []
        try:
            with self.trades_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError as exc:
            log.error("store: could not read trades: %s", exc)
            return []
        if limit is not None:
            return rows[-limit:]
        return rows
