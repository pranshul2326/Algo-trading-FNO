#!/usr/bin/env python3
"""Matheran CLI.

    python run.py selfcheck              validate the indicator maths
    python run.py doctor                 check broker credentials and config
    python run.py chain --underlying NIFTY   print the ATM/OTM scan table
    python run.py serve                  start the API and dashboard
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def cmd_selfcheck(_args) -> int:
    from matheran.selfcheck import main as selfcheck_main

    print("Matheran indicator and strategy self-check\n")
    return selfcheck_main()


def cmd_doctor(args) -> int:
    from matheran.brokers import build_broker
    from matheran.config import load_config

    cfg = load_config(args.config)
    print(f"mode            : {cfg.mode}")
    print(f"broker          : {cfg.broker.name}")
    print(f"timeframe       : {cfg.strategy.timeframe_minutes} min")
    print(f"stop loss       : {cfg.risk.stop_loss_pct}% of capital deployed")
    print(f"warmup bars     : {cfg.strategy.warmup_bars()}")
    print(f"api key set     : {bool(cfg.secrets.api_key)}")
    print(f"dhan creds set  : {bool(cfg.secrets.dhan_access_token and cfg.secrets.dhan_client_id)}")

    async def go() -> int:
        broker = build_broker(cfg)
        print(f"resolved broker : {broker.name} (data: {getattr(broker, 'data_source', broker.name)})")
        try:
            await broker.startup()
            health = await broker.health()
            print("broker health   : ok")
            for k, v in health.items():
                print(f"  {k}: {v}")
            _account_warnings(health, getattr(broker, "data_source", broker.name))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"broker health   : FAILED - {exc}")
            return 1
        finally:
            await broker.shutdown()

    return asyncio.run(go())


def _flatten(node, out: list[dict] | None = None) -> list[dict]:
    """Collect every nested dict in a health payload; composites nest several levels."""
    out = [] if out is None else out
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            _flatten(value, out)
    return out


def _account_warnings(health: dict, data_source: str) -> None:
    """Call out account-level gaps that would stop the strategy working."""
    nodes = _flatten(health)
    warnings: list[str] = []

    # The Dhan Data API plan only matters if Dhan is actually serving market data.
    if "dhan" in data_source:
        for node in nodes:
            plan = str(node.get("data_plan", "")).lower()
            if plan and plan != "active":
                warnings.append(
                    "Dhan Data APIs are NOT subscribed, so candles and quotes will fail "
                    "and no indicator can be computed. Either subscribe on web.dhan.co "
                    "(₹499 + taxes/month) or set broker.data_broker: upstox, which is free "
                    "and needs no credentials."
                )
                break

    for node in nodes:
        segments = str(node.get("active_segments", ""))
        if not segments:
            continue
        active = {s.strip().lower() for s in segments.split(",") if s.strip()}
        if not any(s.startswith("deriv") for s in active):
            warnings.append(
                f"Only these segments are active on your broker account: "
                f"{segments.strip().rstrip(',')}. Placing option orders needs Derivatives "
                "(F&O) activated. Scanning the chain still works, since that is read-only."
            )
        break

    if warnings:
        print("\nattention:")
        for w in warnings:
            print(f"  - {w}")


def cmd_chain(args) -> int:
    from matheran.brokers import build_broker
    from matheran.config import load_config
    from matheran.options import scan_chain, select_chain

    cfg = load_config(args.config)

    async def go() -> int:
        broker = build_broker(cfg)
        await broker.startup()
        try:
            selection = await select_chain(
                broker,
                args.underlying,
                expiry=args.expiry,
                otm_count=args.otm,
                reference=args.reference,
            )
            rows = await scan_chain(
                broker,
                selection,
                cfg.strategy,
                timeframe_minutes=args.timeframe,
                adx_min=args.adx_min,
            )
        finally:
            await broker.shutdown()

        print(
            f"\n{selection.underlying}  expiry {selection.expiry}"
            f"{'  [EXPIRES TODAY]' if selection.expires_today else ''}  "
            f"{selection.reference} {selection.reference_symbol} {selection.spot:.2f}  "
            f"ATM {selection.atm_strike:g}  step {selection.strike_step:g}  "
            f"{args.timeframe}m candles\n"
        )
        head = (
            f"{'CONTRACT':<26}{'TYPE':>5}{'STRIKE':>9}{'MONEY':>7}{'LTP':>10}{'VWAP':>10}"
            f"{'>VWAP':>7}{'RSI':>8}{'EMA(RSI)':>10}{'EMA21':>9}{'SUPERT':>10}{'ADX':>7}{'READY':>7}"
        )
        print(head)
        print("-" * len(head))

        def f(v, nd=2):
            return "-" if v is None else f"{v:.{nd}f}"

        for row in rows:
            d = row.as_dict()
            print(
                f"{(d['display_name'] or d['symbol'])[:26]:<26}"
                f"{d['option_type'] or '':>5}{d['strike'] or 0:>9.0f}{d['moneyness']:>7}"
                f"{f(d['ltp']):>10}{f(d['vwap']):>10}{'yes' if d['price_above_vwap'] else 'no':>7}"
                f"{f(d['rsi']):>8}{f(d['rsi_ema_21']):>10}{f(d['price_ema_21']):>9}"
                f"{f(d['supertrend']):>10}{f(d['adx'],1):>7}"
                f"{'READY' if d['entry_ready'] else 'no':>7}"
            )
            if d["error"]:
                print(f"    error: {d['error']}")

        above = [r for r in rows if r.price_above_vwap]
        ready = [r for r in rows if r.entry_ready]
        print(f"\n{len(above)} strikes trading above VWAP, {len(ready)} meeting every entry condition")
        if ready:
            print("entry-ready:")
            for r in ready:
                print(f"  {r.instrument.display_name}  security_id={r.instrument.security_id}")
        return 0

    return asyncio.run(go())


def cmd_serve(args) -> int:
    import uvicorn

    from matheran.api import create_app
    from matheran.config import load_config

    cfg = load_config(args.config)
    if args.host:
        cfg.server.host = args.host
    if args.port:
        cfg.server.port = args.port

    app = create_app(cfg)
    banner = f"""
  Matheran trading API
  mode        : {cfg.mode.upper()}{"   <-- REAL ORDERS" if cfg.live else "   (orders simulated)"}
  broker      : {cfg.broker.name}
  dashboard   : http://{cfg.server.host}:{cfg.server.port}/
  api docs    : http://{cfg.server.host}:{cfg.server.port}/docs
  auth        : {"X-API-Key required" if cfg.secrets.api_key else "OPEN (no MATHERAN_API_KEY set)"}
"""
    print(banner)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="matheran", description=__doc__,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-c", "--config", default=None, help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("selfcheck", help="validate indicators and strategy wiring").set_defaults(
        func=cmd_selfcheck
    )
    sub.add_parser("doctor", help="check config and broker connectivity").set_defaults(
        func=cmd_doctor
    )

    chain = sub.add_parser("chain", help="print the ATM/OTM options scan table")
    chain.add_argument("--underlying", default="NIFTY")
    chain.add_argument("--expiry", default=None, help="YYYY-MM-DD (default: nearest)")
    chain.add_argument("--otm", type=int, default=5)
    chain.add_argument("--timeframe", type=int, default=1,
                       choices=[1, 3, 5, 9, 15, 30, 60, 120, 1440, 10080, 43200],
                       help="minutes: 60 = 1h, 1440 = 1 day, 10080 = 1 week, 43200 = 1 month")
    chain.add_argument("--reference", default="index", choices=["index", "future"])
    chain.add_argument("--adx-min", dest="adx_min", type=float, default=None)
    chain.set_defaults(func=cmd_chain)

    serve = sub.add_parser("serve", help="run the API and dashboard")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=cmd_serve)

    return p


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    _logging(args.verbose)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
