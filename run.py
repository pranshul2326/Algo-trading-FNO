#!/usr/bin/env python3
"""Saidarshan CLI.

    python run.py selfcheck              validate the indicator maths
    python run.py doctor                 check broker credentials and config
    python run.py chain --underlying NIFTY   print the ATM/OTM scan table
    python run.py scan --universe nifty50    live BUY/SELL scanner (read-only)
    python run.py scan --symbols NSE:RELIANCE,BSE:TCS,MCX:GOLD --side both --values
    python run.py serve                  start the API, the portal (/) and the app (/app)
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

    print("Saidarshan indicator and strategy self-check\n")
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


_CELL = {"true": "✓", "false": "✗", "unavailable": "na", "skipped": "·"}


def _scan_progress(job) -> str:
    s = job.summary()
    eta = s["eta_seconds"]
    matches = ", ".join(f"{k} {v}" for k, v in s["matches"].items())
    wait = ""
    if s["state"] == "waiting":
        wait = f" (budget: until {s['waiting_until'][11:19]})" if s["waiting_until"] else \
            " (waiting for requests in flight)"
    return (f"scan: {s['state']}{wait} {s['scanned']}/{s['total']} · matches {matches} · "
            f"{s['requests']['upstox']} Upstox requests"
            + (f" · ETA {eta:.0f} s" if isinstance(eta, (int, float)) and eta else ""))


def _print_scan(status: dict, *, show_all: bool, values: bool, out) -> None:
    """Header, one table per side, legend, summary and notes (design §6.11)."""
    from matheran.universes import clean_text

    def say(text: str = "") -> None:
        print(text, file=out)

    scan, results = status["scan"], status["results"]
    started = (scan.get("started_at") or "")[:19].replace("T", " ")
    say(f"\nscan {started} IST  side {scan['side']}  evaluation "
        f"{scan.get('evaluation_used') or scan['evaluation']}"
        + (f" ({scan['evaluation_reason']})" if scan.get("evaluation_reason") else ""))
    parts = [f"{clean_text(u['label'])} ({u['size']}, {u['source']}, {u['as_of']})"
             for u in scan.get("universes") or []]
    if scan.get("custom"):
        parts.append(f"custom {scan['custom']}")
    say("universes: " + ("; ".join(parts) or "none"))
    plans = []
    for cls, p in (scan.get("plan") or {}).items():
        src = ", ".join(f"{s['name']} {s['sessions']} sessions" for s in p["sources"])
        today = "1D" if p["today_interval"] >= 1440 else f"{p['today_interval']}m"
        plans.append(f"{cls}: today {today}; {src}")
    say(f"data: {scan.get('data_source')}" + (" (SYNTHETIC)" if scan.get("synthetic") else "")
        + ("   plan " + " | ".join(plans) if plans else ""))

    def fmt(v, nd=2) -> str:
        return "-" if v is None else f"{v:,.{nd}f}"

    for side in scan.get("sides") or []:
        cols = scan["columns"][side]
        rows = [r for r in results if side in r["sides"] or r["status"] == "error"]
        shown = rows if show_all else [r for r in rows if r["sides"].get(side, {}).get("signal")]
        n_match = sum(1 for r in rows if r["sides"].get(side, {}).get("signal"))
        say(f"\n{side}: {n_match} match(es) of {scan['scanned']} scanned"
            + ("" if show_all else "  (--all shows every symbol)"))
        if not shown:
            continue
        def marks(sr: dict) -> list[str]:
            out_marks = []
            for c in sr["rows"]:
                mark = _CELL.get(c["state"], "?")
                if values and c["left"] is not None and c["state"] in ("true", "false"):
                    mark += f"{c['left']:.1f}"
                out_marks.append(mark)
            return out_marks

        w = max([4] + [len(m) + 1 for r in shown if side in r["sides"]
                       for m in marks(r["sides"][side])])
        head = f"{'SYMBOL':<14}{'EXCH':<5}{'LTP':>11}{'CHG%':>8} " + "".join(
            f"{'C' + str(c['index'] + 1):<{w}}" for c in cols) + f"{'MET':>5} {'SIGNAL':<7} NAME"
        say(head)
        say("-" * len(head))
        for r in sorted(shown, key=lambda r: (r["exchange"], r["symbol"])):
            sr = r["sides"].get(side)
            if sr is None:
                cells, met, sig = " " * (w * len(cols)), "", "ERROR"
            else:
                cells = "".join(f"{m:<{w}}" for m in marks(sr))
                met = f"{sr['met']}/{sr['total']}"
                sig = "YES" if sr["signal"] else ("no data" if r["status"] == "no_data" else "no")
            chg = "-" if r["change_pct"] is None else f"{r['change_pct']:+.2f}"
            say(f"{clean_text(r['symbol'], 13):<14}{r['exchange']:<5}{fmt(r['ltp']):>11}{chg:>8} "
                f"{cells}{met:>5} {sig:<7} {clean_text(r['name'], 30)}")

    say("\nlegend:")
    for side in scan.get("sides") or []:
        for c in scan["columns"][side]:
            say(f"  {side} C{c['index'] + 1} = {c['text']}")
    say("  cells: ✓ met · ✗ not met · na not available (counts as not met) · · not checked (lazy)")

    req = scan["requests"]
    budget = scan.get("budget") or {}
    total30 = budget.get("used_scanner_30m", 0)
    ext = scan.get("_external_30m", 0)
    matches = ", ".join(f"{k} {v}" for k, v in scan["matches"].items())
    say(f"\nsummary: scanned {scan['scanned']}/{scan['total']} in {scan['duration_seconds']} s · "
        f"matches {matches} · errors {scan['errors']} · symbols with n/a {scan['na_symbols']} · "
        f"skipped symbols {len(scan.get('skipped') or [])}")
    say(f"requests: {req['upstox']:,} this scan (quotes {req['quotes']})"
        + (f", Dhan {req['dhan']}" if req.get("dhan") else "")
        + (f", other {req['other']}" if req.get("other") else "")
        + f"; scanner total in the last 30 min {total30:,} (incl. {ext:,} from another process)")
    say(f"history cache: {scan['cache']['hits']} hits, {scan['cache']['misses']} misses")

    notes = [clean_text(n, 300) for n in scan.get("notes") or []]
    for r in results:
        if r["error"]:
            notes.append(f"{clean_text(r['symbol'], 30)}: {clean_text(r['error'], 300)}")
        for n in r["notes"]:
            notes.append(f"{clean_text(r['symbol'], 30)}: {clean_text(n, 300)}")
    for s in scan.get("skipped") or []:
        notes.append(f"skipped {clean_text(s['symbol'], 40)}: {clean_text(s['reason'], 300)}")
    if scan.get("message"):
        notes.insert(0, clean_text(scan["message"], 300))
    if notes:
        say("\nnotes:")
        for n in notes:
            say(f"  - {n}")


def cmd_scan(args) -> int:
    import json

    from matheran.brokers import BrokerError, build_broker
    from matheran.brokers.upstox import UPSTOX_REQUESTS
    from matheran.config import load_config
    from matheran.scanner import ScanBusy, ScanManager, ScanSpec
    from matheran.universes import UniverseUnavailable

    cfg = load_config(args.config)
    # --json -: stdout carries only the JSON document; everything else goes to stderr.
    out = sys.stderr if args.json == "-" else sys.stdout
    body: dict = {}
    if args.universe or args.symbols:     # exactly what was given; the saved lists are not merged
        body["universes"] = list(dict.fromkeys(args.universe or []))
        body["custom_symbols"] = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    else:
        body["universes"] = list(cfg.scanner.universes)
        body["custom_symbols"] = list(cfg.scanner.custom_symbols)
    if args.side:
        body["side"] = args.side
    if args.evaluation:
        body["evaluation"] = args.evaluation
    try:
        spec = ScanSpec.build(cfg.scanner, body)
    except ValueError as exc:
        print(f"scan: {exc}", file=sys.stderr)
        return 1

    async def go() -> int:
        broker = build_broker(cfg)
        manager = ScanManager(cfg, broker=broker)
        interrupted = False
        job = None
        try:
            try:
                await broker.startup()
                job = await manager.start(spec)
            except (ScanBusy, BrokerError, ValueError, UniverseUnavailable) as exc:
                print(f"scan: {exc}", file=sys.stderr)
                return 1
            try:
                while not job.task.done():
                    await asyncio.wait({job.task}, timeout=2.0)
                    if not job.task.done():
                        print(_scan_progress(job), file=sys.stderr)
            except asyncio.CancelledError:      # Ctrl-C: cancel, then print the partial results
                interrupted = True
                task = asyncio.current_task()
                if task is not None:
                    task.uncancel()
                job.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(job.task), 5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        finally:
            await manager.shutdown()
            await broker.shutdown()
        status = job.status(0)
        status["scan"]["_external_30m"] = UPSTOX_REQUESTS.count(1800, prefix="scanner:ext")
        _print_scan(status, show_all=args.all, values=args.values, out=out)
        status["scan"].pop("_external_30m", None)
        if args.json:
            doc = json.dumps({"scan": status["scan"], "results": status["results"]},
                             ensure_ascii=False, default=str)
            if args.json == "-":
                sys.stdout.write(doc + "\n")
                sys.stdout.flush()
            else:
                with open(args.json, "w", encoding="utf-8") as fh:
                    fh.write(doc + "\n")
        if interrupted:
            print("\ninterrupted: partial results above", file=sys.stderr)
            return 130
        state = status["scan"]["state"]
        if state == "done":
            return 0
        print(f"scan {state}: {status['scan'].get('message') or ''}", file=sys.stderr)
        return 1

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
  Saidarshan trading API
  mode        : {cfg.mode.upper()}{"   <-- REAL ORDERS" if cfg.live else "   (orders simulated)"}
  broker      : {cfg.broker.name}
  portal      : http://{cfg.server.host}:{cfg.server.port}/
  app         : http://{cfg.server.host}:{cfg.server.port}/app
  api docs    : http://{cfg.server.host}:{cfg.server.port}/docs
  auth        : {"X-API-Key required" if cfg.secrets.api_key else "OPEN (no MATHERAN_API_KEY set)"}
"""
    print(banner)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="saidarshan", description=__doc__,
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

    from matheran.universes import UNIVERSE_IDS

    scan = sub.add_parser(
        "scan", help="live BUY/SELL scanner (read-only)",
        description="Scan universes and/or symbols with the scanner conditions of config.yaml. "
                    "With --universe or --symbols exactly those are scanned; otherwise the saved "
                    "selection. Read-only: no orders, no watches.")
    scan.add_argument("--universe", action="append", choices=UNIVERSE_IDS, default=None,
                      help="repeatable: " + " ".join(UNIVERSE_IDS))
    scan.add_argument("--symbols", default=None, help="comma list, e.g. NSE:RELIANCE,BSE:TCS,MCX:GOLD")
    scan.add_argument("--side", choices=["buy", "sell", "both"], default=None)
    scan.add_argument("--evaluation", choices=["auto", "complete", "lazy"], default=None)
    scan.add_argument("--all", action="store_true", help="print every symbol, not only matches")
    scan.add_argument("--values", action="store_true", help="show each condition's left value")
    scan.add_argument("--json", default=None, metavar="PATH|-",
                      help="write the result JSON to PATH, or to stdout with - (tables go to stderr)")
    scan.set_defaults(func=cmd_scan)

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
