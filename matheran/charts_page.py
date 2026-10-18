"""Multi-pane live chart grid. Plain HTML, plain CSS, vendored Lightweight Charts."""

CHARTS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="/static/ui-theme.js"></script>
<title>Matheran charts</title>
<script src="/static/lightweight-charts.standalone.production.js"></script>
<style>
  :root {
    --bg:#0f1216; --panel:#171c22; --line:#2a323c; --text:#e6edf3; --muted:#9aa7b4;
    --up:#3fb950; --down:#f85149; --accent:#58a6ff; --gap:8px;
  }
  * { box-sizing:border-box; }
  html,body { height:100%; }
  body { margin:0; background:var(--bg); color:var(--text); overflow:hidden;
    font:13px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }

  header { display:flex; gap:12px; align-items:center; flex-wrap:wrap;
    padding:9px 14px; border-bottom:1px solid var(--line); background:#0f1216; }
  h1 { font-size:14px; margin:0; font-weight:650; }
  h1 a { color:var(--muted); text-decoration:none; font-weight:500; margin-left:10px; }
  h1 a:hover { color:var(--accent); }
  .grow { margin-left:auto; }
  label.f { display:flex; flex-direction:column; gap:3px; font-size:11px; color:var(--muted); }
  label.inline { display:flex; align-items:center; gap:6px; font-size:12.5px; color:var(--text); }
  select,input,button { background:#0d1117; color:var(--text); border:1px solid var(--line);
    border-radius:6px; padding:5px 8px; font:inherit; }
  button { background:#21262d; cursor:pointer; }
  button:hover { background:#2d333b; }
  :focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
  .pill { font-size:11.5px; color:var(--muted); border:1px solid var(--line);
    border-radius:999px; padding:2px 9px; }

  /* ---- the grid: one rule per supported count, nothing dynamic in JS ---- */
  main { height:calc(100vh - 47px); padding:var(--gap); }
  .grid { display:grid; gap:var(--gap); height:100%; }
  .grid[data-n="1"] { grid-template-columns:1fr;              grid-template-rows:1fr; }
  .grid[data-n="2"] { grid-template-columns:repeat(2,1fr);    grid-template-rows:1fr; }
  .grid[data-n="4"] { grid-template-columns:repeat(2,1fr);    grid-template-rows:repeat(2,1fr); }
  .grid[data-n="6"] { grid-template-columns:repeat(3,1fr);    grid-template-rows:repeat(2,1fr); }
  .grid[data-n="8"] { grid-template-columns:repeat(4,1fr);    grid-template-rows:repeat(2,1fr); }

  /* Narrower viewports: fewer columns, more rows, charts stay usable. */
  @media (max-width:1400px) {
    .grid[data-n="8"] { grid-template-columns:repeat(3,1fr); grid-template-rows:repeat(3,1fr); }
  }
  @media (max-width:1100px) {
    .grid[data-n="6"], .grid[data-n="8"] {
      grid-template-columns:repeat(2,1fr); grid-template-rows:repeat(4,1fr); }
    .grid[data-n="4"] { grid-template-columns:repeat(2,1fr); grid-template-rows:repeat(2,1fr); }
  }
  @media (max-width:760px) {
    body { overflow:auto; }
    main { height:auto; }
    .grid[data-n] { grid-template-columns:1fr; grid-template-rows:none; }
    .pane { min-height:300px; }
  }

  .pane { background:var(--panel); border:1px solid var(--line); border-radius:8px;
    display:flex; flex-direction:column; min-height:0; min-width:0; overflow:hidden; }
  .bar { display:flex; gap:7px; align-items:center; padding:6px 8px;
    border-bottom:1px solid var(--line); flex-wrap:wrap; }
  .bar select { padding:3px 6px; font-size:12px; max-width:190px; }
  .bar input.sym { padding:3px 7px; font-size:12px; width:240px; font-family:inherit; }
  .bar input.sym.bad { border-color:var(--down); }
  .bar .last { margin-left:auto; font-variant-numeric:tabular-nums; font-size:12.5px; }
  .bar .err { color:var(--down); font-size:11.5px; max-width:230px;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .chart { flex:1; min-height:0; position:relative; }
  .chart .empty { position:absolute; inset:0; display:grid; place-items:center;
    color:var(--muted); font-size:12px; pointer-events:none; }
  .up { color:var(--up); } .down { color:var(--down); } .mut { color:var(--muted); }
  [hidden] { display:none !important; }

  /* Symbol suggestions: one shared list, placed under whichever textbox is active.
     Fixed positioning keeps it from being clipped by the pane it belongs to. */
  ul.sug { position:fixed; z-index:60; margin:0; padding:4px 0; list-style:none;
    background:var(--panel); border:1px solid var(--line); border-radius:8px;
    box-shadow:0 8px 26px #0009; overflow-y:auto; }
  ul.sug li { display:flex; justify-content:space-between; gap:12px; padding:5px 10px;
    font-size:12.5px; cursor:pointer; }
  ul.sug li .grp { color:var(--muted); font-size:11px; white-space:nowrap; }
  ul.sug li[aria-selected="true"], ul.sug li[data-k]:hover { background:#21262d; }
  ul.sug li.none { color:var(--muted); cursor:default; }

  /* Indicator picker: a plain <details> so it needs no JS to open or close. */
  details.drop { position:relative; }
  details.drop > summary { cursor:pointer; list-style:none; background:#21262d;
    border:1px solid var(--line); border-radius:6px; padding:5px 11px; font-size:12.5px; }
  details.drop > summary::-webkit-details-marker { display:none; }
  details.drop > summary::after { content:" ▾"; color:var(--muted); }
  details.drop[open] > summary { border-color:var(--accent); }
  .dropbody { position:absolute; z-index:30; top:calc(100% + 5px); left:0; min-width:300px;
    background:var(--panel); border:1px solid var(--line); border-radius:8px;
    padding:9px 11px; box-shadow:0 8px 26px #0008; }
  .dropbody .indrow { display:flex; align-items:center; gap:8px; padding:3px 0; font-size:12.5px; }
  .dropbody .indrow label { cursor:pointer; }
  .dropbody .sep { border-top:1px solid var(--line); margin:7px 0 5px; padding-top:5px;
    color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  .dropbody .sep:first-child { border-top:none; margin-top:0; padding-top:0; }
  /* Native colour input, trimmed down to look like a swatch. */
  input[type=color].pick { width:22px; height:18px; padding:0; border-radius:3px;
    border:1px solid var(--line); background:none; cursor:pointer; flex:none; }
  input[type=color].pick::-webkit-color-swatch-wrapper { padding:1px; }
  input[type=color].pick::-webkit-color-swatch { border:none; border-radius:2px; }
  .dropbody .foot { border-top:1px solid var(--line); margin-top:8px; padding-top:8px;
    display:flex; gap:8px; }
  .sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0);
    white-space:nowrap; }

  /* Trading from a pane: the Trade button, and a chip for its order or position. */
  button.go { background:#1f6f37; border-color:#2a8f47; }
  button.go:hover:not(:disabled) { background:#25833f; }
  button.sell { background:#6b2026; border-color:#8b2b32; }
  button.sell:hover:not(:disabled) { background:#7d262d; }
  button:disabled { opacity:.45; cursor:not-allowed; }
  .bar button.trade { padding:3px 10px; font-size:12px; }
  .pos { display:flex; gap:7px; align-items:center; font-size:11.5px; border:1px solid var(--line);
    border-radius:999px; padding:1px 3px 1px 9px; font-variant-numeric:tabular-nums;
    white-space:nowrap; }
  .pos.long { border-color:#2a8f47; } .pos.short { border-color:#8b2b32; }
  .pos.wait { border-color:#5c4408; }
  .pos button { padding:1px 9px; font-size:11.5px; border-radius:999px; }

  dialog.ticket { background:var(--panel); color:var(--text); border:1px solid var(--line);
    border-radius:10px; padding:0; width:min(460px, calc(100vw - 20px));
    box-shadow:0 18px 60px #000b; }
  dialog.ticket::backdrop { background:#000a; }
  .tk { padding:14px 16px 12px; display:grid; gap:11px; }
  .tk h2 { margin:0; font-size:15px; font-weight:650; }
  .tk .sub { color:var(--muted); font-size:12px; margin:-7px 0 0; }
  .tk .mode { font-size:12px; border-radius:6px; padding:4px 9px; }
  .tk .mode.paper { background:#12301c; color:#8ee29e; border:1px solid #24502e; }
  .tk .mode.live { background:#4a1218; color:#ffb3b3; border:1px solid #7d232b; font-weight:650; }
  .tk .line { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }
  .tk label.f input { width:118px; }
  .tk fieldset { border:none; margin:0; padding:0; min-width:0; }
  .seg { display:inline-flex; border:1px solid var(--line); border-radius:7px; overflow:hidden; }
  .seg input { position:absolute; opacity:0; width:1px; height:1px; }
  .seg label { padding:6px 14px; cursor:pointer; font-size:12.5px; }
  .seg label + input + label { border-left:1px solid var(--line); }
  .seg input:checked + label { background:#2d333b; font-weight:650; }
  .seg input:focus-visible + label { outline:2px solid var(--accent); outline-offset:-2px; }
  .seg.side input[value=BUY]:checked + label { background:#1f6f37; }
  .seg.side input[value=SELL]:checked + label { background:#6b2026; }
  .levels { display:grid; grid-template-columns:auto 118px auto 1fr; gap:7px 9px;
    align-items:center; font-size:12.5px; }
  .levels select { padding:5px 6px; }
  .levels .hint { font-size:11.5px; color:var(--muted); }
  .tk .hint { font-size:11.5px; color:var(--muted); }
  .tk .preview { font-size:12.5px; background:#0d1117; border:1px solid var(--line);
    border-radius:7px; padding:8px 10px; display:grid; gap:3px; font-variant-numeric:tabular-nums; }
  .tk .preview:empty { display:none; }
  .tk .err { color:#ffb3b3; font-size:12.5px; margin:0; }
  .tk .err:empty { display:none; }
  .tk .actions { display:flex; justify-content:flex-end; gap:8px; }
  .tk select { padding:5px 7px; }
  .levels input:disabled, .levels select:disabled { opacity:.4; }

  /* Chart type, Renko box and the countdown to the candle's close, in each pane bar. */
  .bar select.ctype { max-width:118px; }
  .bar input.box { width:78px; padding:3px 6px; font-size:12px; }
  .bar .cd { font-variant-numeric:tabular-nums; font-size:11.5px; color:var(--muted);
    white-space:nowrap; }

  /* Drawing tools: one toolbar, used on whichever chart you click. */
  .tools { display:flex; gap:2px; align-items:center; border:1px solid var(--line);
    border-radius:7px; padding:2px; }
  .tools button { padding:3px 7px; font-size:13px; border:1px solid transparent; background:transparent;
    border-radius:5px; min-width:28px; line-height:1.2; }
  .tools button:hover:not(:disabled) { background:#21262d; }
  .tools button[aria-pressed="true"] { background:#1b2a44; border-color:#264a7a; color:#cfe3ff; }
  .tools input[type=color] { width:24px; height:22px; padding:0; border:1px solid var(--line);
    border-radius:4px; background:none; cursor:pointer; }
  .chart.drawing { cursor:crosshair; }

  /* Indicator parameters, under their row in the picker. */
  .dropbody .pp { display:flex; gap:6px; align-items:center; padding:0 0 5px 52px; font-size:11.5px;
    color:var(--muted); flex-wrap:wrap; }
  .dropbody .pp input { width:62px; padding:2px 5px; font-size:12px; }
  .dropbody .pp input.bad { border-color:var(--down); }
  .dropbody .pp select { padding:2px 5px; font-size:12px; }

  body { display:flex; flex-direction:column; }
  main { flex:1; min-height:0; height:auto; }
  ul.sug { max-width:calc(100vw - 16px); }
  @media (max-width:760px) {
    header { padding:7px 8px; gap:8px; align-items:center; }
    header > h1 { width:100%; }
    header .grow { display:none; }
    header label.f, header details.drop { flex:1 1 118px; min-width:0; }
    header select, header details.drop > summary { width:100%; }
    .tools { order:20; flex:1 1 100%; width:100%; max-width:100%; flex-wrap:nowrap;
      overflow-x:auto; -webkit-overflow-scrolling:touch; }
    .tools button { min-width:44px; min-height:44px; flex:none; }
    .tools input[type=color] { width:44px; height:44px; flex:none; }
    main { width:100%; padding:6px; }
    .grid .pane { min-height:360px; }
    .bar input.sym { width:100%; flex:1 1 100%; max-width:100%; }
    .bar select { flex:1 1 92px; max-width:100%; min-width:0; }
    .dropbody { position:fixed; top:8px; left:8px; right:8px; width:auto; min-width:0;
      max-height:calc(100dvh - 16px); overflow:auto; }
    ul.sug { left:8px !important; width:calc(100vw - 16px) !important; }
    dialog.ticket { max-height:calc(100dvh - 16px); overflow:auto; }
    .tk { padding:12px 10px; }
    .levels { grid-template-columns:auto minmax(0,1fr) auto minmax(80px,1fr); }
    .levels input, .tk label.f input { max-width:100%; min-width:0; }
  }
</style>
<link rel="stylesheet" href="/static/ui-theme.css" />
</head>
<body>
<header>
  <h1>Matheran charts <a href="/">← console</a> <a href="/chain">option chain ↗</a>
    <a href="/combo">basket combo ↗</a></h1>
  <label class="f" for="count">Number of charts
    <select id="count">
      <option value="1">1 — full screen</option>
      <option value="2">2 — side by side</option>
      <option value="4">4 — 2 × 2</option>
      <option value="6">6 — 3 × 2</option>
      <option value="8">8 — 4 × 2</option>
    </select>
  </label>
  <label class="f" for="source">Data source
    <select id="source"></select>
  </label>
  <label class="f" for="refresh">Refresh
    <select id="refresh">
      <option value="0">off</option>
      <option value="5000" selected>5s</option>
      <option value="15000">15s</option>
      <option value="60000">60s</option>
    </select>
  </label>
  <label class="inline" for="sync" title="Pan or zoom one chart and the rest follow">
    <input type="checkbox" id="sync" /> Sync time axis
  </label>
  <details id="indBox" class="drop">
    <summary>Indicators &amp; colours</summary>
    <div class="dropbody" id="indList"></div>
  </details>
  <div class="tools" role="toolbar" aria-label="Drawing tools" id="tools">
    <button type="button" data-tool="cursor" aria-pressed="true" aria-label="Pointer"
      title="Pointer: click a drawing to select it, drag it or its ends to move it (Esc)">↖</button>
    <button type="button" data-tool="trend" aria-pressed="false" aria-label="Trend line"
      title="Trend line: click two points, or drag">╱</button>
    <button type="button" data-tool="ray" aria-pressed="false" aria-label="Ray"
      title="Ray: a line carried on past its second point">⟶</button>
    <button type="button" data-tool="hline" aria-pressed="false" aria-label="Horizontal line"
      title="Horizontal line at a price">―</button>
    <button type="button" data-tool="vline" aria-pressed="false" aria-label="Vertical line"
      title="Vertical line at a time">│</button>
    <button type="button" data-tool="rect" aria-pressed="false" aria-label="Rectangle"
      title="Box: click two corners, or drag">▭</button>
    <button type="button" data-tool="fib" aria-pressed="false" aria-label="Fibonacci retracement"
      title="Fibonacci retracement: from the start of the move to its end">ƒ</button>
    <button type="button" data-tool="text" aria-pressed="false" aria-label="Text note"
      title="Text note">T</button>
    <input type="color" id="drawColour" value="#58a6ff" aria-label="Drawing colour"
      title="Colour for new drawings, and for the selected one" />
    <button type="button" id="drawDelete" aria-label="Delete the selected drawing"
      title="Delete the selected drawing (Delete key)" disabled>✕</button>
    <button type="button" id="drawClear" aria-label="Clear drawings"
      title="Remove every drawing on the chart you last clicked">Clear</button>
  </div>
  <label class="theme-picker" for="themeSelect">Theme
    <select id="themeSelect" data-theme-select><option value="night">Night</option><option value="light">Light</option></select>
  </label>
  <div class="grow"></div>
  <span id="status" class="pill" role="status" aria-live="polite">…</span>
  <button id="reset" type="button" title="Forget saved layout and panes">Reset</button>
</header>

<ul id="sugbox" class="sug" role="listbox" aria-label="Matching symbols" hidden></ul>
<main><div class="grid" id="grid" data-n="4"></div></main>

<dialog id="ticket" class="ticket" aria-labelledby="tkTitle">
  <form id="tkForm" class="tk" novalidate>
    <h2 id="tkTitle">Trade</h2>
    <p class="sub" id="tkSub"></p>
    <div id="tkMode" class="mode paper">PAPER · orders are simulated</div>

    <div class="line">
      <fieldset class="seg side"><legend class="sr">Side</legend>
        <input type="radio" name="tkSide" id="tkBuy" value="BUY" checked /><label for="tkBuy">Buy</label>
        <input type="radio" name="tkSide" id="tkSell" value="SELL" /><label for="tkSell">Sell</label>
      </fieldset>
      <label class="f" for="tkLots"><span id="tkLotsLabel">Lots</span>
        <input id="tkLots" type="number" min="1" step="1" value="1" inputmode="numeric" /></label>
      <span class="hint" id="tkQty"></span>
    </div>

    <div class="line">
      <fieldset class="seg"><legend class="sr">Order type</legend>
        <input type="radio" name="tkType" id="tkMkt" value="MARKET" checked /><label for="tkMkt">Market</label>
        <input type="radio" name="tkType" id="tkLmt" value="LIMIT" /><label for="tkLmt">Limit</label>
        <input type="radio" name="tkType" id="tkGtt" value="GTT" /><label for="tkGtt"
          title="Good till triggered: held by the engine and sent when the live price reaches the trigger">GTT</label>
      </fieldset>
    </div>

    <div class="line" id="tkPriceLine" hidden>
      <label class="f" for="tkTrig" id="tkTrigWrap">Trigger price
        <input id="tkTrig" type="number" min="0" step="0.05" inputmode="decimal" /></label>
      <label class="f" for="tkLimit" id="tkLimitWrap"><span id="tkLimitLabel">Limit price</span>
        <input id="tkLimit" type="number" min="0" step="0.05" inputmode="decimal" /></label>
      <span class="hint" id="tkTrigHint"></span>
    </div>

    <div class="levels">
      <label for="tkSl">Stop loss</label>
      <input id="tkSl" type="number" min="0" step="any" inputmode="decimal" />
      <select id="tkSlUnit" aria-label="Stop loss as"><option value="pct">%</option><option value="price">price</option></select>
      <span class="hint" id="tkSlHint"></span>

      <label for="tkTrail">Trailing SL</label>
      <input id="tkTrail" type="number" min="0" step="any" inputmode="decimal" placeholder="off" />
      <select id="tkTrailUnit" aria-label="Trailing stop as"><option value="pct">%</option><option value="pts">points</option></select>
      <span class="hint" id="tkTrailHint"></span>

      <label for="tkTrailAfter">Trail after</label>
      <input id="tkTrailAfter" type="number" min="0" step="any" inputmode="decimal" placeholder="entry" />
      <span class="hint">% profit</span>
      <span class="hint" id="tkTrailAfterHint">trailing profit: blank trails from the entry</span>

      <label for="tkTp">Target</label>
      <input id="tkTp" type="number" min="0" step="any" inputmode="decimal" placeholder="none" />
      <select id="tkTpUnit" aria-label="Target as"><option value="pct">%</option><option value="price">price</option></select>
      <span class="hint" id="tkTpHint"></span>
    </div>

    <div class="line">
      <fieldset class="seg"><legend class="sr">Product</legend>
        <input type="radio" name="tkProd" id="tkMis" value="INTRADAY" checked /><label for="tkMis"
          title="Squared off at the square-off time">Intraday</label>
        <input type="radio" name="tkProd" id="tkCnc" value="DELIVERY" /><label for="tkCnc"
          title="Carried overnight: CNC for shares, NRML for futures and options">Delivery</label>
      </fieldset>
      <label class="f" for="tkExit">Exit by
        <select id="tkExit">
          <option value="both">SL / target + exit conditions</option>
          <option value="sl_target">SL / target only</option>
          <option value="strategy">Exit conditions only</option>
        </select></label>
    </div>
    <p class="hint" id="tkExitHint" style="margin:-4px 0 0"></p>

    <div class="preview" id="tkPreview" aria-live="polite"></div>
    <p class="err" id="tkErr" role="alert"></p>
    <div class="actions">
      <button type="button" id="tkClose">Cancel</button>
      <button type="submit" id="tkSubmit" class="go">Place BUY order</button>
    </div>
  </form>
</dialog>

<script>
"use strict";
const LWC = window.LightweightCharts;
const $ = (id) => document.getElementById(id);
const STORE = "matheranCharts.v1";
const COUNTS = [1, 2, 4, 6, 8];
const KEY = sessionStorage.getItem("mthKey") || "";

const DEFAULTS = ["idx:NIFTY", "idx:BANKNIFTY", "eq:NSE:RELIANCE", "eq:NSE:TCS",
                  "eq:NSE:HDFCBANK", "eq:NSE:INFY", "eq:NSE:SBIN", "eq:NSE:ITC"];

// Colours for what is not an indicator. Indicator defaults come from the server's
// catalog, so the engine and the chart agree on what each line is.
const BASE_COLOURS = { "candles:up": "#3fb950", "candles:down": "#f85149" };

// Timeframes, replaced by the server's list at boot. Older saved layouts used 60m.
let TIMEFRAMES = ["1m", "3m", "5m", "9m", "15m", "30m", "1h", "2h", "1D", "1W", "1M"];
let TF_MIN = { "1m": 1, "3m": 3, "5m": 5, "9m": 9, "15m": 15, "30m": 30, "1h": 60, "2h": 120,
               "1D": 1440, "1W": 10080, "1M": 43200 };
const TF_ALIAS = { "60m": "1h", "120m": "2h", "1H": "1h", "2H": "2h", "1d": "1D", "D": "1D",
                   "1w": "1W", "W": "1W", "M": "1M" };
const normTf = (tf) => (tf && TF_MIN[tf] ? tf : (TF_ALIAS[tf] || null));
const CHART_TYPES = [["candles", "Candles"], ["heikin_ashi", "Heikin Ashi"], ["renko", "Renko"]];

let state = load();
let panes = [];
let timer = null;
let syncing = false;
let CATALOG = [];
// Symbol id -> {id, label, group}. Filled by every search and by chart metadata, so
// a pane can show a friendly name for whatever id it holds.
const known = new Map();

function newPane(symbol, timeframe) {
  return { symbol, timeframe: timeframe || "5m", chartType: "candles", box: "" };
}
function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE) || "null");
    if (raw && COUNTS.includes(raw.count) && Array.isArray(raw.panes)) {
      for (const p of raw.panes) {
        if (!p) continue;
        p.timeframe = normTf(p.timeframe) || "5m";
        if (!CHART_TYPES.some(([id]) => id === p.chartType)) p.chartType = "candles";
        if (p.box == null) p.box = "";
      }
      if (!raw.indParams || typeof raw.indParams !== "object") raw.indParams = {};
      return raw;
    }
  } catch (e) { /* fall through to defaults */ }
  return {
    count: 4,
    source: "broker",
    refresh: 5000,
    sync: false,
    indicators: null,   // filled from the server's defaults on first boot
    indParams: {},      // indicator id -> its parameters (ZEMA period, Supertrend timeframe...)
    colours: {},        // colour key -> user-chosen hex (see colourFor)
    ticket: null,       // last stop / trail / target used on the trade ticket
    panes: DEFAULTS.map((s) => newPane(s, "5m")),
  };
}

/* The console links here with ?symbols=a,b&tf=5m to open specific instruments —
   an option contract alongside its underlying, or a basket beside its legs. */
function applyUrlRequest() {
  const p = new URLSearchParams(location.search);
  const raw = p.get("symbols") || p.get("symbol");
  if (!raw) return false;
  const wanted = raw.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 8);
  if (!wanted.length) return false;
  const tf = normTf(p.get("tf") || p.get("timeframe"));
  if (!COUNTS.includes(state.count) || state.count < wanted.length) {
    state.count = COUNTS.find((c) => c >= wanted.length) || 8;
  }
  wanted.forEach((sym, i) => {
    const old = state.panes[i] || {};
    state.panes[i] = { ...newPane(sym, tf || old.timeframe || "5m"),
                       chartType: old.chartType || "candles", box: old.box || "" };
  });
  save();
  // Leave the address bar clean so a reload does not re-apply the same request.
  history.replaceState(null, "", location.pathname);
  return true;
}
function save() { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }

async function api(path, opts = {}) {
  const h = { "Accept": "application/json" };
  if (opts.body) h["Content-Type"] = "application/json";
  if (KEY) h["X-API-Key"] = KEY;
  const res = await fetch(path, { ...opts, headers: h });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = { detail: text }; }
  if (!res.ok) {
    const d = body && body.detail;
    // Validation errors arrive as a list of {loc, msg}; show the messages, not JSON.
    const msg = typeof d === "string" ? d
      : Array.isArray(d) ? d.map((x) => (x && x.msg) || JSON.stringify(x)).join("; ")
      : res.statusText;
    throw new Error(msg);
  }
  return body;
}
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
const fmt = (v) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toFixed(2);

function setStatus(text, bad) {
  $("status").textContent = text;
  $("status").style.color = bad ? "var(--down)" : "var(--muted)";
}
function chartThemeOptions() {
  const css = getComputedStyle(document.documentElement);
  const value = (name) => css.getPropertyValue(name).trim();
  return {
    layout: { background: { color: value("--chart-bg") }, textColor: value("--chart-text"),
              attributionLogo: false },
    grid: { vertLines: { color: value("--chart-grid") }, horzLines: { color: value("--chart-grid") } },
    rightPriceScale: { borderColor: value("--chart-border") },
    timeScale: { borderColor: value("--chart-border") },
  };
}

/* ------------------------------------------------------------------ colours */
function colour(key, fallback) {
  return (state.colours && state.colours[key]) || fallback;
}
/* The chosen colour for an indicator line. Two-colour indicators (Supertrend) keep
   their downtrend colour under "<id>:down". */
function colourFor(spec, side) {
  if (side === "down") return colour(spec.id + ":down", spec.color_down || spec.color);
  return colour(spec.id, spec.color);
}
function candleColours() {
  return { up: colour("candles:up", BASE_COLOURS["candles:up"]),
           down: colour("candles:down", BASE_COLOURS["candles:down"]) };
}
function candleOptions() {
  const c = candleColours();
  return { upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down,
           borderVisible: false };
}
function rgba(hex, alpha) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || ""));
  if (!m) return hex;
  const v = parseInt(m[1], 16);
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${alpha})`;
}
function volumePoint(b) {
  const c = candleColours();
  return { time: b.time, value: b.volume, color: rgba(b.close >= b.open ? c.up : c.down, 0.35) };
}

/* ------------------------------------------------------------- IST axis */
// Bar times are UNIX seconds and the library labels them in UTC, which put the
// 09:15 open at "03:45". Every label is rendered in IST instead.
const IST_MS = 5.5 * 3600 * 1000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad2 = (v) => String(v).padStart(2, "0");
function istParts(t) {
  const d = new Date(Number(t) * 1000 + IST_MS);   // shifted, then read as UTC
  return { y: d.getUTCFullYear(), mo: d.getUTCMonth(), d: d.getUTCDate(),
           h: d.getUTCHours(), mi: d.getUTCMinutes() };
}
function istTick(time, type) {
  const p = istParts(time);
  if (type === 0) return String(p.y);                 // TickMarkType.Year
  if (type === 1) return MONTHS[p.mo];                // Month
  if (type === 2) return `${p.d} ${MONTHS[p.mo]}`;    // DayOfMonth
  return `${pad2(p.h)}:${pad2(p.mi)}`;                // Time
}
function istCrosshair(time) {
  const p = istParts(time);
  return `${p.d} ${MONTHS[p.mo]} ${p.y}  ${pad2(p.h)}:${pad2(p.mi)} IST`;
}

/* --------------------------------------------------------------- chart pane */
function makePane(index) {
  const cfg = state.panes[index] || newPane(DEFAULTS[index % 8], "5m");
  state.panes[index] = cfg;

  const el = document.createElement("section");
  el.className = "pane";
  el.innerHTML = `
    <div class="bar">
      <input class="sym" type="text" id="sym${index}" role="combobox"
             aria-autocomplete="list" aria-expanded="false" aria-controls="sugbox"
             aria-label="Symbol for chart ${index + 1}" autocomplete="off"
             spellcheck="false" placeholder="type a stock, index, option or basket" />
      <select class="tf" aria-label="Timeframe for chart ${index + 1}" id="tf${index}"></select>
      <select class="ctype" aria-label="Chart type for chart ${index + 1}" id="ct${index}">
        ${CHART_TYPES.map(([id, label]) => `<option value="${id}">${label}</option>`).join("")}
      </select>
      <input class="box" type="number" min="0" step="any" inputmode="decimal" id="box${index}"
             placeholder="box: ATR" aria-label="Renko box size for chart ${index + 1}"
             title="Renko box size in price. Blank uses ATR(14) of the timeframe." hidden />
      <span class="last mut" id="last${index}">—</span>
      <span class="cd" id="cd${index}" title="Time left in the current candle"></span>
      <span class="pos" id="pos${index}" hidden></span>
      <button type="button" class="trade go" id="trade${index}">Trade</button>
      <span class="err" id="err${index}" hidden></span>
    </div>
    <div class="chart" id="c${index}"><div class="empty">loading…</div></div>`;
  $("grid").appendChild(el);

  const host = el.querySelector(".chart");
  const theme = chartThemeOptions();
  const chart = LWC.createChart(host, {
    layout: theme.layout,
    grid: theme.grid,
    rightPriceScale: { ...theme.rightPriceScale, scaleMargins: { top: 0.08, bottom: 0.26 } },
    localization: { timeFormatter: istCrosshair },
    timeScale: { ...theme.timeScale, timeVisible: true, secondsVisible: false,
                 rightOffset: 3, tickMarkFormatter: istTick },
    crosshair: { mode: LWC.CrosshairMode.Normal },
    autoSize: true,
  });

  // v5 API: series types are passed as the first argument to addSeries, and the
  // third argument is the pane index (0 = price, 1 = RSI, 2 = ADX).
  const candles = chart.addSeries(LWC.CandlestickSeries, candleOptions());
  const volume = chart.addSeries(LWC.HistogramSeries, {
    priceFormat: { type: "volume" }, priceScaleId: "vol",
  });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

  const pane = {
    index, el, chart, candles, volume, cfg,
    ind: {},          // indicator id -> [series] (two series for up/down indicators)
    bars: [],         // bars last drawn, so a colour change can repaint the volume
    lastTime: 0, loaded: false,
    meta: null,       // lot and tick size of the symbol on screen
    ltp: null,        // latest close drawn
    lines: [],        // price lines for this pane's order or position
    lineSig: "",
    emptyEl: host.querySelector(".empty"),
    lastEl: el.querySelector(`#last${index}`),
    errEl: el.querySelector(`#err${index}`),
    symEl: el.querySelector(`#sym${index}`),
    tfEl: el.querySelector(`#tf${index}`),
    ctEl: el.querySelector(`#ct${index}`),
    boxEl: el.querySelector(`#box${index}`),
    cdEl: el.querySelector(`#cd${index}`),
    posEl: el.querySelector(`#pos${index}`),
    tradeEl: el.querySelector(`#trade${index}`),
    host,
    clock: null,      // when the candle forming now closes (server time), for the countdown
    cdText: null,     // countdown last drawn
    realLast: null,   // real last and previous close (a Heikin Ashi close is an average)
    realPrev: null,
  };

  fillTimeframes(pane);
  showSymbol(pane);
  buildIndicatorSeries(pane);
  wireSymbolBox(pane);
  updateTradeButton(pane);
  pane.tradeEl.onclick = () => openTicket(pane);
  pane.tfEl.onchange = () => {
    cfg.timeframe = pane.tfEl.value; save(); reload(pane);
  };
  pane.ctEl.value = cfg.chartType || "candles";
  pane.boxEl.value = cfg.box || "";
  pane.boxEl.hidden = pane.ctEl.value !== "renko";
  pane.ctEl.onchange = () => {
    cfg.chartType = pane.ctEl.value;
    pane.boxEl.hidden = cfg.chartType !== "renko";
    save(); reload(pane);
  };
  pane.boxEl.onchange = () => {
    const v = Number(pane.boxEl.value);
    cfg.box = pane.boxEl.value.trim() && v > 0 ? String(v) : "";
    pane.boxEl.value = cfg.box;
    save(); reload(pane);
  };

  // Drawings ride on the candle series as a primitive, so they pan and zoom with it.
  pane.layer = new DrawingLayer(pane);
  pane.candles.attachPrimitive(pane.layer);
  wireDrawing(pane);

  if (state.sync) attachSync(pane);
  return pane;
}

/* ------------------------------------------------------------- indicators */
function buildIndicatorSeries(pane) {
  // Drop anything no longer selected, then add what is missing. Rebuilding only the
  // delta keeps toggling cheap and leaves the price pane untouched.
  for (const [id, list] of Object.entries(pane.ind)) {
    if (!state.indicators.includes(id)) {
      for (const series of list) { try { pane.chart.removeSeries(series); } catch (e) {} }
      delete pane.ind[id];
    }
  }
  for (const spec of CATALOG) {
    if (!state.indicators.includes(spec.id) || pane.ind[spec.id]) continue;
    const base = {
      lineWidth: spec.color_down ? 2 : 1,
      priceLineVisible: false, lastValueVisible: !spec.overlay,
      title: spec.overlay ? "" : spec.id,
    };
    if (spec.color_down) {
      // One series per trend side, each carrying values only while its side is
      // active. The line therefore breaks at a flip instead of drawing a diagonal
      // from one band to the other, and each side takes its own colour.
      pane.ind[spec.id] = [
        pane.chart.addSeries(LWC.LineSeries, { ...base, color: colourFor(spec, "up") }, spec.pane),
        pane.chart.addSeries(LWC.LineSeries, { ...base, color: colourFor(spec, "down") }, spec.pane),
      ];
    } else {
      pane.ind[spec.id] = [
        pane.chart.addSeries(LWC.LineSeries, { ...base, color: colourFor(spec) }, spec.pane),
      ];
    }
  }
  // Give the price pane the lion's share of the height.
  try {
    const list = pane.chart.panes();
    if (list.length > 1) {
      list[0].setStretchFactor(3);
      for (let i = 1; i < list.length; i++) list[i].setStretchFactor(1);
    }
  } catch (e) { /* older builds without pane stretch */ }
}

function setIndicatorData(pane, id, points) {
  const list = pane.ind[id];
  if (!list) return;
  if (list.length === 2) {
    // trend -1 is an uptrend (first series), +1 a downtrend (second). A bare
    // {time} is whitespace, which is what breaks the line.
    list[0].setData(points.map((p) =>
      p.trend === -1 ? { time: p.time, value: p.value } : { time: p.time }));
    list[1].setData(points.map((p) =>
      p.trend === -1 ? { time: p.time } : { time: p.time, value: p.value }));
    return;
  }
  list[0].setData(points.map((p) => ({ time: p.time, value: p.value })));
}

function fillTimeframes(pane) {
  if (!TIMEFRAMES.includes(pane.cfg.timeframe)) pane.cfg.timeframe = normTf(pane.cfg.timeframe) || "5m";
  pane.tfEl.innerHTML = TIMEFRAMES.map((t) =>
    `<option value="${t}" ${t === pane.cfg.timeframe ? "selected" : ""}>${t}</option>`).join("");
}

/* -------------------------------------------------------- symbol textbox */
function labelFor(id) {
  const s = known.get(id);
  return s ? s.label : id;
}
/* Show the friendly name in the box but keep the id in state. */
function showSymbol(pane) {
  pane.symEl.value = labelFor(pane.cfg.symbol);
  pane.symEl.title = pane.cfg.symbol;
}
/* Chart metadata names panes that were opened by id (from a link or a basket). */
function rememberMeta(id, meta) {
  if (!meta || known.has(id)) return;
  let label = meta.display_name || id;
  if (id.startsWith("eq:")) label = `${meta.symbol} — ${String(meta.display_name || "").slice(0, 34)}`;
  else if (id.startsWith("idx:")) label = `${meta.symbol} (spot)`;
  else if (id.startsWith("opt:") || id.startsWith("fut:")) label = meta.symbol || label;
  known.set(id, { id, label, group: "" });
}

/* Turn whatever was typed into a symbol id.

   Accepts an exact id (eq:/idx:/opt:/fut:/basket:), a suggestion label, or a bare
   ticker. `strict` is used when focus simply leaves the box: only recognisable
   text is taken, so half-typed input snaps back instead of loading garbage. */
function resolveTyped(raw, strict) {
  const text = (raw || "").trim();
  if (!text) return null;
  const m = /^(eq|idx|opt|fut|mcx|basket):(.+)$/i.exec(text);
  if (m) {
    const kind = m[1].toLowerCase();
    return kind + ":" + (kind === "basket" ? m[2] : m[2].toUpperCase());
  }
  const up = text.toUpperCase();
  for (const s of known.values()) if (s.label === text) return s.id;
  for (const s of known.values()) {
    if (s.label.toUpperCase() === up || s.id.toUpperCase() === up) return s.id;
  }
  // Tickers can contain "-" and "&" (BAJAJ-AUTO, M&M), so only a space or the
  // label's em dash ends one.
  const ticker = up.split(/[\s—]/)[0].trim();
  if (!ticker) return null;
  for (const id of ["eq:NSE:" + ticker, "idx:" + ticker]) if (known.has(id)) return id;
  return strict ? null : "eq:NSE:" + ticker;
}

const sug = { pane: null, items: [], active: -1, timer: null, seq: 0 };

function wireSymbolBox(pane) {
  const box = pane.symEl;
  box.addEventListener("input", () => {
    box.classList.remove("bad");
    clearTimeout(sug.timer);
    sug.timer = setTimeout(() => runSearch(pane), 180);
  });
  box.addEventListener("keydown", (ev) => {
    const open = sug.pane === pane && !$("sugbox").hidden;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      if (open) moveActive(1); else runSearch(pane);
    } else if (ev.key === "ArrowUp") {
      if (open) { ev.preventDefault(); moveActive(-1); }
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      clearTimeout(sug.timer);
      if (open && sug.active >= 0) pickSymbol(pane, sug.items[sug.active]);
      else commitTyped(pane, false);
    } else if (ev.key === "Escape") {
      if (open) { ev.preventDefault(); closeSuggest(); }
      showSymbol(pane);
    }
  });
  box.addEventListener("focus", () => box.select());
  box.addEventListener("blur", () => {
    clearTimeout(sug.timer);
    if (sug.pane === pane) closeSuggest();
    if (box.value.trim() !== labelFor(pane.cfg.symbol)) commitTyped(pane, true);
  });
}

async function runSearch(pane) {
  const text = pane.symEl.value.trim();
  const seq = ++sug.seq;
  const q = new URLSearchParams({ q: text, limit: "30", source: state.source });
  try {
    const d = await api("/api/charts/symbols?" + q.toString());
    // A newer keystroke, or focus moving away, makes this answer stale.
    if (seq !== sug.seq || document.activeElement !== pane.symEl) return;
    const list = d.symbols || [];
    for (const s of list) known.set(s.id, s);
    openSuggest(pane, list, text);
  } catch (e) {
    if (seq === sug.seq) closeSuggest();
  }
}

function openSuggest(pane, items, text) {
  const box = $("sugbox");
  sug.pane = pane; sug.items = items; sug.active = -1;
  box.innerHTML = items.length
    ? items.map((s, k) => `<li role="option" id="sug-${k}" data-k="${k}" aria-selected="false">
        <span>${esc(s.label)}</span><span class="grp">${esc(s.group || "")}</span></li>`).join("")
    : `<li class="none" role="option" aria-disabled="true">No match${text ? " for “" + esc(text) + "”" : ""}
        — Enter tries it as an NSE ticker</li>`;
  const r = pane.symEl.getBoundingClientRect();
  const width = Math.max(r.width, 340);
  box.style.left = Math.max(4, Math.min(r.left, window.innerWidth - width - 4)) + "px";
  box.style.top = Math.round(r.bottom + 3) + "px";
  box.style.width = width + "px";
  box.style.maxHeight = Math.max(140, Math.min(340, window.innerHeight - r.bottom - 14)) + "px";
  box.hidden = false;
  pane.symEl.setAttribute("aria-expanded", "true");
  pane.symEl.removeAttribute("aria-activedescendant");
}

function closeSuggest() {
  const box = $("sugbox");
  box.hidden = true;
  box.innerHTML = "";
  if (sug.pane) {
    sug.pane.symEl.setAttribute("aria-expanded", "false");
    sug.pane.symEl.removeAttribute("aria-activedescendant");
  }
  sug.pane = null; sug.items = []; sug.active = -1;
}

function moveActive(delta) {
  if (!sug.items.length || !sug.pane) return;
  sug.active = (sug.active + delta + sug.items.length) % sug.items.length;
  $("sugbox").querySelectorAll("li[data-k]").forEach((li) => {
    const on = Number(li.dataset.k) === sug.active;
    li.setAttribute("aria-selected", on ? "true" : "false");
    if (on) li.scrollIntoView({ block: "nearest" });
  });
  sug.pane.symEl.setAttribute("aria-activedescendant", "sug-" + sug.active);
}

function setPaneSymbol(pane, id) {
  pane.symEl.classList.remove("bad");
  if (selected && selected.pane === pane) selectDrawing(null);
  pane.cfg.symbol = id;
  pane.meta = null;
  pane.ltp = null;
  pane.clock = null;
  showSymbol(pane);
  updateTradeButton(pane);
  renderPaneTrade(pane);
  save();
  reload(pane);
}
function pickSymbol(pane, ref) {
  if (!ref) return;
  known.set(ref.id, ref);
  closeSuggest();
  if (ref.id === pane.cfg.symbol) { showSymbol(pane); return; }
  setPaneSymbol(pane, ref.id);
}
function commitTyped(pane, strict) {
  const id = resolveTyped(pane.symEl.value, strict);
  closeSuggest();
  if (!id) {
    if (strict) showSymbol(pane);
    else pane.symEl.classList.add("bad");
    return;
  }
  if (id === pane.cfg.symbol) { showSymbol(pane); return; }
  setPaneSymbol(pane, id);
}

// Picking with the mouse must not blur the textbox first, or the blur handler
// would commit the half-typed text before the click lands.
$("sugbox").addEventListener("mousedown", (ev) => {
  ev.preventDefault();
  const li = ev.target.closest("li[data-k]");
  if (li && sug.pane) pickSymbol(sug.pane, sug.items[Number(li.dataset.k)]);
});
window.addEventListener("resize", closeSuggest);

/* ----------------------------------------------------------------- data */
async function reload(pane) {
  pane.loaded = false;
  pane.lastTime = 0;
  await refreshPane(pane);
}

/* What a pane is showing; an answer for anything else arrived too late to use. */
const paneSig = (pane) => [pane.cfg.symbol, pane.cfg.timeframe, pane.cfg.chartType || "candles",
                           pane.cfg.box || ""].join("|");

/* Parameters of the active indicators that have them, as the candles endpoint reads them. */
function paramsFor(ids) {
  const out = {};
  for (const id of ids) {
    const spec = CATALOG.find((s) => s.id === id);
    if (!spec || !(spec.params || []).length) continue;
    const vals = (state.indParams || {})[id];
    if (vals && Object.keys(vals).length) out[id] = vals;
  }
  return Object.keys(out).length ? JSON.stringify(out) : "";
}

async function refreshPane(pane) {
  const sig = paneSig(pane);
  const symbol = pane.cfg.symbol, timeframe = pane.cfg.timeframe;
  const chartType = pane.cfg.chartType || "candles";
  const q = new URLSearchParams({ symbol, timeframe, source: state.source, chart_type: chartType });
  if (chartType === "renko" && pane.cfg.box) q.set("box", pane.cfg.box);
  if (state.indicators.length) {
    q.set("indicators", state.indicators.join(","));
    const params = paramsFor(state.indicators);
    if (params) q.set("params", params);
  }
  try {
    const d = await api("/api/charts/candles?" + q.toString());
    // The pane was re-pointed while this was in flight; its answer belongs to nobody.
    if (paneSig(pane) !== sig) return;
    const bars = d.bars || [];
    pane.errEl.hidden = true;
    if (d.meta) {
      pane.meta = d.meta;
      rememberMeta(symbol, d.meta);
      if (document.activeElement !== pane.symEl) showSymbol(pane);
    }
    if (!bars.length) {
      pane.emptyEl.textContent = chartType === "renko"
        ? "no bricks yet: the price has not moved a whole box" : "no data for this symbol / timeframe";
      pane.emptyEl.hidden = false;
      return;
    }
    pane.emptyEl.hidden = true;

    if (!pane.loaded || chartType === "renko") {
      // Renko is redrawn whole, since a brick built on the live price can vanish when
      // the price pulls back. A view scrolled back into history is held in place.
      const ts = pane.chart.timeScale();
      let keep = null;
      if (pane.loaded) {
        const lr = ts.getVisibleLogicalRange();
        if (lr && lr.to < pane.bars.length - 1.5) keep = ts.getVisibleRange();
      }
      pane.candles.setData(bars);
      pane.volume.setData(bars.map(volumePoint));
      if (!pane.loaded) ts.fitContent();
      else if (keep) { try { ts.setVisibleRange(keep); } catch (e) {} }
      pane.loaded = true;
    } else {
      // Only push bars at or after the newest one we already drew, so zoom and pan
      // survive the refresh.
      for (const b of bars) {
        if (b.time < pane.lastTime) continue;
        pane.candles.update(b);
        pane.volume.update(volumePoint(b));
      }
    }
    pane.bars = bars;
    // Indicator series are always re-seeded: they are small, and a partial update
    // would leave stale points behind when the warmup window shifts.
    const series = d.indicators || {};
    for (const [id, points] of Object.entries(series)) setIndicatorData(pane, id, points);

    pane.lastTime = bars[bars.length - 1].time;

    // The real prices: on Heikin Ashi and Renko the last bar is not the last trade.
    const lastClose = d.last_price != null ? d.last_price : bars[bars.length - 1].close;
    const prevClose = d.prev_price != null ? d.prev_price
      : (bars.length > 1 ? bars[bars.length - 2].close : lastClose);
    pane.ltp = lastClose;
    pane.clock = d.clock
      ? { ...d.clock, offset: d.clock.server_time - Date.now() / 1000,
          minutes: d.timeframe_minutes || TF_MIN[timeframe] || 5 }
      : null;
    tickCountdown(pane);
    renderPaneTrade(pane);
    const chg = lastClose - prevClose;
    const pct = prevClose ? (chg / Math.abs(prevClose)) * 100 : 0;
    pane.lastEl.className = "last " + (chg > 0 ? "up" : chg < 0 ? "down" : "mut");
    pane.lastEl.textContent =
      `${fmt(lastClose)}  ${chg >= 0 ? "+" : ""}${fmt(chg)} (${chg >= 0 ? "+" : ""}${pct.toFixed(2)}%)`;
    pane.lastEl.title = chartType === "candles" ? "" : "last traded price, not the "
      + (chartType === "renko" ? `last brick (box ${fmt(d.box)})` : "Heikin Ashi close");
    if (d.name) pane.symEl.title = d.name + "  ·  " + symbol;
    pane.layer.update();
  } catch (e) {
    if (paneSig(pane) !== sig) return;
    pane.errEl.hidden = false;
    pane.errEl.textContent = e.message;
    pane.errEl.title = e.message;
    pane.emptyEl.hidden = pane.loaded;
    if (!pane.loaded) pane.emptyEl.textContent = "failed to load";
  }
}

/* --------------------------------------------------------------- countdown */
/* Time left in the candle now forming, shown beside the last price on the axis (as on
   TradingView) and in the pane bar. Between refreshes it rolls on to the next bar by
   itself, inside the session. */
function fmtLeft(s) {
  s = Math.max(0, Math.floor(s));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (d > 0) return `${d}d ${pad2(h)}h`;
  if (h > 0) return `${h}:${pad2(m)}:${pad2(sec)}`;
  return `${pad2(m)}:${pad2(sec)}`;
}
function countdownText(pane) {
  const c = pane.clock;
  if (!c) return "";
  const now = Date.now() / 1000 + c.offset;
  let end = c.bar_close;
  if (end <= now && c.minutes < 1440 && c.trading_day && now >= c.session_open && now < c.session_close) {
    const step = c.minutes * 60;
    end = Math.min(c.session_open + Math.ceil((now - c.session_open + 0.001) / step) * step, c.session_close);
  }
  return end > now ? fmtLeft(end - now) : "closed";
}
function tickCountdown(pane) {
  const text = countdownText(pane);
  if (text === pane.cdText) return;
  pane.cdText = text;
  pane.cdEl.textContent = text ? (text === "closed" ? "candle closed" : "⏱ " + text) : "";
  pane.cdEl.title = text === "closed" ? "No candle forming: the market is closed for this timeframe"
                                      : "Time left in the current candle";
  try { pane.candles.applyOptions({ title: text && text !== "closed" ? text : "" }); } catch (e) {}
}
setInterval(() => panes.forEach(tickCountdown), 1000);

/* ------------------------------------------------------------------ trading */
let STATUS = null;   // /api/status: mode and the risk defaults
let MODE = "paper";
let TRADES = [];     // /api/charts/trades: GTTs, working entries, open positions
let ticketPane = null;
let ticketOpener = null;
let limitTouched = false;  // the limit price was typed, so defaults leave it alone

const LINE = { solid: 0, dotted: 1, dashed: 2 };
const isLive = () => MODE === "live";
const defaultStopPct = () => (STATUS && STATUS.risk && STATUS.risk.stop_loss_pct) || 3;

async function loadStatus() {
  try {
    STATUS = await api("/api/status");
    MODE = STATUS.mode || MODE;
  } catch (e) { /* the panes report auth and connection problems */ }
  panes.forEach(updateTradeButton);
}
async function loadTrades() {
  try {
    const d = await api("/api/charts/trades");
    TRADES = d.trades || [];
    if (d.mode) MODE = d.mode;
  } catch (e) { /* keep the last known list */ }
}
async function refreshTrades() {
  await loadTrades();
  panes.forEach(renderPaneTrade);
}

function tradeFor(pane) {
  return TRADES.find((t) => (t.symbols || []).includes(pane.cfg.symbol));
}

function updateTradeButton(pane) {
  const sym = pane.cfg.symbol || "";
  let why = "";
  if (sym.startsWith("idx:")) why = "An index spot cannot be traded; chart its future or an option";
  else if (sym.startsWith("basket:")) why = "Baskets are executed from the console's Baskets tab";
  else if (sym.startsWith("mcx:")) {
    why = "MCX commodities can be charted but not traded here: the engine trades NSE/BSE equities and NSE/BSE F&O";
  }
  else if (STATUS && STATUS.risk && STATUS.risk.allow_manual_buy === false) {
    why = "Manual orders are switched off on the Strategy tab";
  }
  pane.tradeEl.disabled = !!why;
  pane.tradeEl.title = why || "Buy or sell this symbol: market, limit or GTT, with stop, trailing stop and target";
}

/* The pane's chip and price lines: a pending GTT, a working limit, or the position. */
function renderPaneTrade(pane) {
  const t = tradeFor(pane);
  const levels = [];
  let html = "", cls = "pos";
  if (t) {
    const p = t.position, tk = t.ticket, o = t.entry_order;
    if (p) {
      const sign = p.direction === "SHORT" ? -1 : 1;
      const pnl = pane.ltp == null ? null : (pane.ltp - p.entry_price) * p.quantity * sign;
      cls += sign < 0 ? " short" : " long";
      html = `<span>${sign < 0 ? "SHORT" : "LONG"} ${p.quantity} @ ${fmt(p.entry_price)}${
          p.product === "DELIVERY" ? ' <span class="mut">delivery</span>' : ""}</span>
        <span class="${pnl > 0 ? "up" : pnl < 0 ? "down" : "mut"}">${pnl == null ? "" : (pnl >= 0 ? "+" : "") + fmt(pnl)}</span>
        ${t.state === "exit_placed" ? '<span class="mut">exiting…</span>'
          : '<button type="button" class="sell" data-act="exit">Exit</button>'}`;
      levels.push({ price: p.entry_price, title: "entry", color: "#9aa7b4", style: LINE.dashed });
      if (p.exit_mode !== "strategy") {
        // A position that exits on its conditions only has no stop or target to draw.
        const stopTitle = p.trailed ? (p.trail_trigger_pct ? "trailing profit" : "trailing SL") : "SL";
        levels.push({ price: p.stop_price, title: stopTitle, color: "#f85149", style: LINE.solid });
        if (p.target_price) levels.push({ price: p.target_price, title: "target", color: "#3fb950", style: LINE.solid });
      }
    } else if (t.state === "gtt_pending" && tk) {
      cls += " wait";
      html = `<span>GTT ${esc(tk.side)} ${tk.quantity} ${tk.trigger_above ? "≥" : "≤"} ${fmt(tk.trigger_price)}</span>
        <button type="button" data-act="cancel">Cancel</button>`;
      levels.push({ price: tk.trigger_price, title: "GTT " + tk.side, color: "#d29922", style: LINE.dotted });
      if (tk.limit_price) levels.push({ price: tk.limit_price, title: "limit", color: "#58a6ff", style: LINE.dotted });
    } else if (t.state === "entry_placed" && o) {
      cls += " wait";
      html = `<span>${o.order_type === "LIMIT"
          ? `LIMIT ${esc(o.side)} ${o.quantity} @ ${fmt(o.price)}` : `${esc(o.side)} ${o.quantity} sent…`}</span>
        <button type="button" data-act="cancel">Cancel</button>`;
      if (o.order_type === "LIMIT") {
        levels.push({ price: o.price, title: "limit " + o.side, color: "#58a6ff", style: LINE.dotted });
      }
    }
    if (html && t.last_error) html += `<span class="down" title="${esc(t.last_error)}">⚠</span>`;
  }
  pane.posEl.hidden = !html;
  pane.posEl.className = cls;
  pane.posEl.innerHTML = html;
  pane.posEl.title = t ? (t.last_error || t.notes || "") : "";
  pane.posEl.querySelectorAll("[data-act]").forEach((b) => {
    b.onclick = () => (b.dataset.act === "exit" ? exitTrade(t) : cancelTrade(t));
  });
  // Rebuilt only when a level changed, so the lines do not flicker on every refresh.
  const sig = JSON.stringify(levels);
  if (sig === pane.lineSig) return;
  for (const line of pane.lines) { try { pane.candles.removePriceLine(line); } catch (e) {} }
  pane.lines = levels.filter((l) => l.price > 0).map((l) => pane.candles.createPriceLine({
    price: l.price, color: l.color, lineWidth: 1, lineStyle: l.style,
    axisLabelVisible: true, title: l.title }));
  pane.lineSig = sig;
}

async function exitTrade(t) {
  if (!confirm((isLive() ? "LIVE — REAL MONEY\n\n" : "Paper mode (simulated)\n\n") +
      `Exit ${t.label} at market now?`)) return;
  try {
    await api(`/api/watches/${encodeURIComponent(t.watch_id)}/exit`, { method: "POST" });
    setStatus(`exit sent for ${t.label}`);
  } catch (e) { setStatus(e.message, true); }
  await refreshTrades();
}
async function cancelTrade(t) {
  const what = t.state === "gtt_pending" ? "the pending GTT" : "the working entry order";
  if (!confirm(`Cancel ${what} on ${t.label}?`)) return;
  try {
    await api(`/api/watches/${encodeURIComponent(t.watch_id)}/cancel`, { method: "POST" });
    setStatus(`cancelled ${what} on ${t.label}`);
  } catch (e) { setStatus(e.message, true); }
  await refreshTrades();
}

/* ------------------------------------------------------------ trade ticket */
function lotOf(pane) { return Math.max(1, Number((pane.meta || {}).lot_size) || 1); }
function tickOf(pane) { return Number((pane.meta || {}).tick_size) || 0.05; }
const radio = (name) => document.querySelector(`input[name="${name}"]:checked`).value;
function numIn(id) {
  const v = $(id).value.trim();
  return v === "" ? null : Number(v);
}
function setRadio(name, value) {
  const el = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (el) el.checked = true;
}

function openTicket(pane) {
  if (pane.tradeEl.disabled) return;
  ticketPane = pane;
  ticketOpener = document.activeElement;
  const lot = lotOf(pane), tick = tickOf(pane);
  const fno = lot > 1 || /^(opt|fut):/.test(pane.cfg.symbol);
  $("tkTitle").textContent = "Trade " + labelFor(pane.cfg.symbol);
  $("tkSub").textContent = `LTP ${fmt(pane.ltp)} · ${fno ? "lot size " + lot : "cash, 1 share per unit"}` +
    ` · tick ${tick} · ${pane.cfg.timeframe} chart`;
  $("tkMode").className = "mode " + (isLive() ? "live" : "paper");
  $("tkMode").textContent = isLive() ? "LIVE · this sends a REAL order to your broker"
                                     : "PAPER · orders are simulated";
  $("tkLotsLabel").textContent = fno ? "Lots" : "Shares";
  for (const id of ["tkLimit", "tkTrig"]) {
    $(id).step = String(tick);
    $(id).value = "";
    $(id).placeholder = pane.ltp != null ? "LTP " + Number(pane.ltp).toFixed(2) : "";
  }
  limitTouched = false;
  // The stop, trail and target you used last time, or the Strategy tab's defaults.
  const last = state.ticket || {};
  const risk = (STATUS && STATUS.risk) || {};
  const firstUse = !state.ticket;
  $("tkSl").value = last.sl != null ? last.sl : defaultStopPct();
  $("tkSlUnit").value = last.slUnit || "pct";
  $("tkTrail").value = last.trail != null ? last.trail
    : (firstUse && risk.trail_profit_value ? risk.trail_profit_value : "");
  $("tkTrailUnit").value = last.trailUnit || (firstUse && risk.trail_profit_unit) || "pct";
  $("tkTrailAfter").value = last.trailAfter != null ? last.trailAfter
    : (firstUse && risk.trail_profit_trigger_pct ? risk.trail_profit_trigger_pct : "");
  $("tkTp").value = last.tp != null ? last.tp : "";
  $("tkTpUnit").value = last.tpUnit || "pct";
  $("tkExit").value = last.exitMode || (last.rules === false ? "sl_target" : "") || risk.exit_mode || "both";
  setRadio("tkProd", last.product || risk.default_product || "INTRADAY");
  if (last.slUnit === "price" || last.tpUnit === "price") {
    // An absolute price from another symbol would be meaningless here.
    if (last.slUnit === "price") { $("tkSl").value = defaultStopPct(); $("tkSlUnit").value = "pct"; }
    if (last.tpUnit === "price") { $("tkTp").value = ""; $("tkTpUnit").value = "pct"; }
  }
  setRadio("tkSide", "BUY");
  setRadio("tkType", last.type || "MARKET");
  $("tkLots").value = "1";
  $("tkErr").textContent = "";
  updateTicket();
  $("ticket").showModal();
  $("tkLots").focus();
  $("tkLots").select();
}

function ticketValues() {
  return {
    side: radio("tkSide"), type: radio("tkType"), lots: numIn("tkLots"),
    limit: numIn("tkLimit"), trigger: numIn("tkTrig"),
    sl: numIn("tkSl"), slUnit: $("tkSlUnit").value,
    trail: numIn("tkTrail"), trailUnit: $("tkTrailUnit").value, trailAfter: numIn("tkTrailAfter"),
    tp: numIn("tkTp"), tpUnit: $("tkTpUnit").value,
    product: radio("tkProd"), exitMode: $("tkExit").value,
  };
}

/* The same arithmetic the engine uses, so the preview is what gets armed. */
function ticketPlan(v, pane) {
  const qty = (v.lots || 0) * lotOf(pane);
  const ltp = pane.ltp;
  const ref = v.type === "MARKET" ? ltp : v.type === "LIMIT" ? v.limit : (v.limit || v.trigger);
  const sign = v.side === "BUY" ? 1 : -1;
  const priceExits = v.exitMode !== "strategy";
  const problems = [];
  if (!(v.lots > 0) || !Number.isInteger(v.lots)) problems.push("lots must be a whole number above 0");
  if (v.type === "LIMIT" && !(v.limit > 0)) problems.push("enter a limit price");
  if (v.type === "GTT" && !(v.trigger > 0)) problems.push("enter a trigger price");
  if (v.type === "MARKET" && !(ltp > 0)) problems.push("no price on the chart yet");
  if (v.product === "DELIVERY" && v.side === "SELL" && pane.cfg.symbol.startsWith("eq:")) {
    problems.push("shares sold short cannot be carried as delivery; use Intraday");
  }
  if (v.exitMode === "strategy" && STATUS && STATUS.has_exit_rules === false) {
    problems.push("no exit conditions are set on the Strategy tab, so nothing would close it");
  }
  if (priceExits) {
    for (const [label, x] of [["stop loss", v.sl], ["trailing stop", v.trail], ["target", v.tp],
                              ["trail after", v.trailAfter]]) {
      if (x != null && !(x > 0)) problems.push(label + " must be above 0, or blank");
    }
    if (v.trailAfter > 0 && !(v.trail > 0)) problems.push("a trailing profit needs a trailing distance");
  }
  let stop = null, target = null, trailDist = null;
  if (ref > 0 && priceExits) {
    if (v.sl > 0) stop = v.slUnit === "price" ? v.sl : ref * (1 - sign * v.sl / 100);
    if (v.trail > 0) {
      trailDist = v.trailUnit === "pts" ? v.trail : ref * v.trail / 100;
      // A trailing profit waits for its trigger; a plain trail starts at the entry.
      if (!(v.trailAfter > 0)) {
        const trailStop = ref - sign * trailDist;
        if (stop == null || (trailStop - stop) * sign > 0) stop = trailStop;
      }
    }
    if (stop == null) stop = ref * (1 - sign * defaultStopPct() / 100);
    if (v.tp > 0) target = v.tpUnit === "price" ? v.tp : ref * (1 + sign * v.tp / 100);
    if ((ref - stop) * sign <= 0) {
      problems.push(`stop ${fmt(stop)} must be ${sign > 0 ? "below" : "above"} the entry ${fmt(ref)}`);
    }
    if (target != null && (target - ref) * sign <= 0) {
      problems.push(`target ${fmt(target)} must be ${sign > 0 ? "above" : "below"} the entry ${fmt(ref)}`);
    }
  }
  return { qty, ref, stop, target, trailDist, sign, problems };
}

function updateTicket() {
  const pane = ticketPane;
  if (!pane) return;
  // A limit order starts at the chart's price; a GTT starts with no limit (market once
  // triggered). Either default gives way as soon as a price is typed.
  if (!limitTouched) {
    const want = radio("tkType") === "LIMIT" && pane.ltp != null ? Number(pane.ltp).toFixed(2) : "";
    if ($("tkLimit").value !== want) $("tkLimit").value = want;
  }
  const v = ticketValues();
  $("tkPriceLine").hidden = v.type === "MARKET";
  $("tkTrigWrap").hidden = v.type !== "GTT";
  $("tkLimitLabel").textContent = v.type === "GTT" ? "Limit price (blank = market)" : "Limit price";
  $("tkLimit").required = v.type === "LIMIT";
  const lot = lotOf(pane);
  $("tkQty").textContent = lot > 1 && v.lots > 0 ? `= ${v.lots * lot} qty` : "";
  $("tkSlHint").textContent = $("tkSlUnit").value === "pct" ? "of the entry" : "stop price";
  $("tkTrailHint").textContent = $("tkTrailUnit").value === "pct"
    ? "behind the best price" : "points behind the best price";
  $("tkTpHint").textContent = $("tkTpUnit").value === "pct" ? "from the entry" : "target price";
  // Exit conditions only: no stop, trail or target, so their boxes are switched off.
  const noPriceExits = v.exitMode === "strategy";
  for (const id of ["tkSl", "tkSlUnit", "tkTrail", "tkTrailUnit", "tkTrailAfter", "tkTp", "tkTpUnit"]) {
    $(id).disabled = noPriceExits;
  }
  $("tkTrailAfterHint").textContent = v.trailAfter > 0
    ? `the trail starts once the trade is ${v.trailAfter}% in profit`
    : "trailing profit: blank trails from the entry";
  const tfText = `<strong>${esc(pane.cfg.timeframe)}</strong>`;
  $("tkExitHint").innerHTML = (
    v.exitMode === "strategy" ? `No stop loss or target: only the exit conditions on ${tfText} candles close it`
    : v.exitMode === "sl_target" ? "Only the stop, trailing stop and target close it; exit conditions are ignored"
    : `The stop, trailing stop, target, or the exit conditions on ${tfText} candles, whichever comes first`)
    + (v.product === "DELIVERY" ? ". Delivery: carried overnight, not squared off." : ". Intraday: squared off at the square-off time.");
  if (v.type === "GTT" && v.trigger > 0 && pane.ltp > 0) {
    $("tkTrigHint").textContent = v.trigger >= pane.ltp
      ? `fires when LTP rises to ${fmt(v.trigger)} or above`
      : `fires when LTP falls to ${fmt(v.trigger)} or below`;
  } else if (v.type === "LIMIT" && v.limit > 0 && pane.ltp > 0) {
    const resting = v.side === "BUY" ? v.limit < pane.ltp : v.limit > pane.ltp;
    $("tkTrigHint").textContent = resting ? "rests until the price comes to it"
                                          : "at or through the market: fills now";
  } else {
    $("tkTrigHint").textContent = "";
  }

  const plan = ticketPlan(v, pane);
  const sideWord = v.side === "BUY" ? "BUY" : "SELL";
  $("tkSubmit").textContent = v.type === "GTT" ? `Arm GTT ${sideWord}` : `Place ${sideWord} order`;
  $("tkSubmit").className = v.side === "BUY" ? "go" : "sell";
  const pct = (x) => plan.ref > 0 ? ((x - plan.ref) / plan.ref * 100) : 0;
  const money = (x) => "₹" + Math.abs(x).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  const lines = [];
  if (plan.ref > 0) {
    lines.push(`<div>Entry ≈ <strong>${fmt(plan.ref)}</strong> ${v.type === "MARKET" ? "(market)" : v.type === "LIMIT" ? "(limit)" : v.limit ? "(GTT, then limit)" : "(GTT, then market)"} · ${plan.qty} qty · ${money(plan.ref * plan.qty)}</div>`);
    if (v.exitMode === "strategy") {
      lines.push(`<div class="down">No stop loss: the exit conditions alone decide${
        v.product === "DELIVERY" ? "" : ", or the square-off"}</div>`);
    } else {
      if (plan.stop != null) {
        lines.push(`<div>Stop <strong class="down">${fmt(plan.stop)}</strong> (${pct(plan.stop).toFixed(2)}%) · risk ${money((plan.ref - plan.stop) * plan.qty * plan.sign)}${plan.trailDist
          ? (v.trailAfter > 0 ? ` · after +${v.trailAfter}%, trails ${fmt(plan.trailDist)} behind the best price`
                              : ` · trails ${fmt(plan.trailDist)} behind the best price`) : ""}</div>`);
      }
      lines.push(plan.target != null
        ? `<div>Target <strong class="up">${fmt(plan.target)}</strong> (${pct(plan.target) >= 0 ? "+" : ""}${pct(plan.target).toFixed(2)}%) · ${money((plan.target - plan.ref) * plan.qty * plan.sign)}</div>`
        : `<div class="mut">No target${v.exitMode === "both" ? "; exit conditions and the stop close it" : "; the stop closes it"}</div>`);
    }
  }
  $("tkPreview").innerHTML = lines.join("");
  $("tkErr").textContent = plan.problems[0] || "";
  $("tkSubmit").disabled = plan.problems.length > 0;
}

$("tkLimit").addEventListener("input", () => { limitTouched = true; });
$("tkForm").addEventListener("input", updateTicket);
$("tkForm").addEventListener("change", updateTicket);
$("tkClose").onclick = () => $("ticket").close();
$("ticket").addEventListener("close", () => {
  if (ticketOpener && typeof ticketOpener.focus === "function") ticketOpener.focus();
  ticketPane = null;
});
$("tkForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const pane = ticketPane;
  if (!pane) return;
  const v = ticketValues();
  const plan = ticketPlan(v, pane);
  if (plan.problems.length) { $("tkErr").textContent = plan.problems[0]; return; }
  if (isLive() && !confirm(`LIVE — REAL MONEY\n\n${v.type} ${v.side} ${plan.qty} × ` +
      `${labelFor(pane.cfg.symbol)} · ${v.product}\n` +
      (v.exitMode === "strategy" ? "No stop: exit conditions only"
        : `Stop ${fmt(plan.stop)}` + (plan.target != null ? ` · target ${fmt(plan.target)}` : "")) +
      "\n\nSend it?")) return;
  const priceExits = v.exitMode !== "strategy";
  const body = {
    symbol: pane.cfg.symbol, side: v.side, lots: v.lots, order_type: v.type,
    limit_price: v.type === "MARKET" ? null : v.limit,
    trigger_price: v.type === "GTT" ? v.trigger : null,
    sl_value: priceExits ? v.sl : null, sl_unit: v.slUnit,
    trail_value: priceExits ? v.trail : null, trail_unit: v.trailUnit,
    trail_trigger_pct: priceExits && v.trail > 0 && v.trailAfter > 0 ? v.trailAfter : null,
    target_value: priceExits ? v.tp : null, target_unit: v.tpUnit,
    exit_mode: v.exitMode, product: v.product,
    timeframe: pane.cfg.timeframe, confirm: true,
  };
  state.ticket = { type: v.type, sl: v.sl, slUnit: v.slUnit, trail: v.trail,
                   trailUnit: v.trailUnit, trailAfter: v.trailAfter, tp: v.tp, tpUnit: v.tpUnit,
                   exitMode: v.exitMode, product: v.product };
  save();
  $("tkSubmit").disabled = true;
  try {
    const r = await api("/api/charts/trade", { method: "POST", body: JSON.stringify(body) });
    const w = r.watch || {};
    $("ticket").close();
    setStatus(w.position
      ? `${v.side} ${w.position.quantity} filled @ ${fmt(w.position.entry_price)} · stop ${fmt(w.position.stop_price)}`
      : w.state === "gtt_pending" ? `GTT armed: ${(r.ticket && r.ticket.text) || ""}`
      : `${v.type} ${v.side} order working at the broker`);
    await refreshTrades();
  } catch (e) {
    $("tkErr").textContent = e.message;
  } finally {
    $("tkSubmit").disabled = false;
  }
};

/* ----------------------------------------------------------------- drawings */
/* Lines, rays, horizontal and vertical lines, boxes, Fibonacci retracements and text,
   drawn on the price pane. A drawing belongs to the symbol, not the pane, so it shows
   on every chart of that symbol, at any timeframe. Points are stored as (time, price)
   and placed between bars by interpolation, so a line drawn on 5-minute candles lands
   in the same place on 1-minute or hourly ones. Kept in this browser's localStorage. */
const DRAW_STORE = "matheranCharts.drawings.v1";
const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const TWO_POINT = new Set(["trend", "ray", "rect", "fib"]);
const NEAR_PX = 6;
let drawings = loadDrawings();   // chart symbol -> [drawing]
let tool = "cursor";
let selected = null;             // { pane, id }
let draft = null;                // { pane, d, x, y }: a two-point drawing being placed
let drag = null;                 // { pane, d, part, start, startLx, orig }
let activePane = null;           // the pane last clicked, for Clear

function loadDrawings() {
  try {
    const d = JSON.parse(localStorage.getItem(DRAW_STORE) || "{}");
    return d && typeof d === "object" && !Array.isArray(d) ? d : {};
  } catch (e) { return {}; }
}
function saveDrawings() {
  for (const k of Object.keys(drawings)) if (!drawings[k] || !drawings[k].length) delete drawings[k];
  try { localStorage.setItem(DRAW_STORE, JSON.stringify(drawings)); } catch (e) {}
}
const listFor = (symbol) => drawings[symbol] || [];
function redrawSymbol(symbol) {
  for (const p of panes) if (p.cfg.symbol === symbol && p.layer) p.layer.update();
}
function findDrawing(sel) {
  return sel ? listFor(sel.pane.cfg.symbol).find((d) => d.id === sel.id) || null : null;
}

/* Time <-> logical bar index, interpolated between bars and extrapolated past either
   end at the timeframe's bar length. */
const barSeconds = (pane) => (TF_MIN[pane.cfg.timeframe] || 5) * 60;
function timeToLogical(pane, t) {
  const b = pane.bars, n = b.length;
  if (!n) return null;
  if (t <= b[0].time) return (t - b[0].time) / barSeconds(pane);
  if (t >= b[n - 1].time) return n - 1 + (t - b[n - 1].time) / barSeconds(pane);
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (b[mid].time <= t) lo = mid; else hi = mid; }
  const span = b[hi].time - b[lo].time;
  return lo + (span > 0 ? (t - b[lo].time) / span : 0);
}
function logicalToTime(pane, x) {
  const b = pane.bars, n = b.length;
  if (!n) return null;
  if (x <= 0) return Math.round(b[0].time + x * barSeconds(pane));
  if (x >= n - 1) return Math.round(b[n - 1].time + (x - (n - 1)) * barSeconds(pane));
  const i = Math.floor(x);
  return Math.round(b[i].time + (x - i) * (b[i + 1].time - b[i].time));
}
/* The library places whole bar indexes only, so fractions are interpolated here. */
function lxToX(pane, lx) {
  const ts = pane.chart.timeScale();
  const x0 = ts.logicalToCoordinate(0), x1 = ts.logicalToCoordinate(1);
  return x0 == null || x1 == null ? null : x0 + lx * (x1 - x0);
}
function xToLx(pane, x) {
  const ts = pane.chart.timeScale();
  const x0 = ts.logicalToCoordinate(0), x1 = ts.logicalToCoordinate(1);
  return x0 == null || x1 == null || x1 === x0 ? null : (x - x0) / (x1 - x0);
}
function toXY(pane, pt) {
  if (!pt) return null;
  const lx = timeToLogical(pane, pt.t);
  if (lx == null) return null;
  const x = lxToX(pane, lx), y = pane.candles.priceToCoordinate(pt.p);
  return x == null || y == null ? null : { x, y };
}
/* A pointer position as (time, price), the time snapped to a bar like the crosshair. */
function fromXY(pane, x, y) {
  const lx = xToLx(pane, x), p = pane.candles.coordinateToPrice(y);
  if (lx == null || p == null) return null;
  return { t: logicalToTime(pane, Math.round(lx)), p: Number(p) };
}

class DrawingLayer {
  constructor(pane) {
    this.pane = pane;
    this.request = null;
    const layer = this;
    this.views = [{ zOrder: () => "top", renderer: () => ({ draw: (target) => layer.draw(target) }) }];
  }
  attached(param) { this.request = param.requestUpdate; }
  detached() { this.request = null; }
  updateAllViews() {}
  paneViews() { return this.views; }
  update() { if (this.request) this.request(); }
  draw(target) {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      try { paintDrawings(this.pane, context, mediaSize); } catch (e) { /* never break the chart */ }
    });
  }
}

function seg(ctx, a, b) { ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
/* Where a ray from a through b leaves the pane. */
function rayEnd(a, b, size) {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (!dx && !dy) return b;
  const k = Math.max(1, dx ? ((dx > 0 ? size.width : 0) - a.x) / dx : ((dy > 0 ? size.height : 0) - a.y) / dy);
  return { x: a.x + dx * k, y: a.y + dy * k };
}
const fibPrice = (d, level) => d.p2.p + (d.p1.p - d.p2.p) * level;

function paintDrawings(pane, ctx, size) {
  const list = listFor(pane.cfg.symbol).slice();
  if (draft && draft.pane === pane) list.push(draft.d);
  if (!list.length || !pane.bars.length) return;
  ctx.save();
  ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
  ctx.textBaseline = "middle";
  for (const d of list) {
    const a = toXY(pane, d.p1), b = d.p2 ? toXY(pane, d.p2) : null;
    if (!a) continue;
    const isSel = selected && selected.pane === pane && selected.id === d.id;
    ctx.strokeStyle = ctx.fillStyle = d.color || "#58a6ff";
    ctx.lineWidth = isSel ? 2.5 : 1.5;
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    if (d.type === "trend" && b) seg(ctx, a, b);
    else if (d.type === "ray" && b) seg(ctx, a, rayEnd(a, b, size));
    else if (d.type === "hline") {
      seg(ctx, { x: 0, y: a.y }, { x: size.width, y: a.y });
      ctx.textAlign = "right";
      ctx.fillText(fmt(d.p1.p), size.width - 6, a.y - 8);
    } else if (d.type === "vline") seg(ctx, { x: a.x, y: 0 }, { x: a.x, y: size.height });
    else if (d.type === "rect" && b) {
      const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y), w = Math.abs(b.x - a.x), h = Math.abs(b.y - a.y);
      ctx.globalAlpha = 0.13; ctx.fillRect(x, y, w, h);
      ctx.globalAlpha = 1; ctx.strokeRect(x, y, w, h);
    } else if (d.type === "fib" && b) {
      const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x, x0 + 40);
      ctx.setLineDash([4, 4]); ctx.lineWidth = 1; seg(ctx, a, b); ctx.setLineDash([]);
      ctx.lineWidth = isSel ? 2 : 1;
      ctx.textAlign = "left";
      for (const level of FIB_LEVELS) {
        const price = fibPrice(d, level), y = pane.candles.priceToCoordinate(price);
        if (y == null) continue;
        seg(ctx, { x: x0, y }, { x: x1, y });
        ctx.fillText(`${level}  ${fmt(price)}`, x1 + 4, y);
      }
    } else if (d.type === "text") {
      ctx.font = "12.5px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(d.text || "", a.x + 3, a.y);
      ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    }
    if (isSel) {
      ctx.fillStyle = "#0f1216";
      ctx.lineWidth = 1.5;
      for (const p of [a, b]) {
        if (!p) continue;
        ctx.beginPath(); ctx.rect(p.x - 4, p.y - 4, 8, 8); ctx.fill(); ctx.stroke();
      }
    }
  }
  ctx.restore();
}

function distToSeg(px, py, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, len = dx * dx + dy * dy;
  const k = len ? Math.max(0, Math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / len)) : 0;
  return Math.hypot(px - (a.x + k * dx), py - (a.y + k * dy));
}
function paneSize(pane) {
  let h = pane.host.clientHeight;
  try { h = pane.chart.panes()[0].getHeight(); } catch (e) { /* single pane */ }
  return { width: pane.chart.timeScale().width(), height: h };
}
/* The drawing under the pointer, newest first, and which part: an end or the body. */
function hitTest(pane, x, y) {
  const size = paneSize(pane);
  const list = listFor(pane.cfg.symbol);
  for (let i = list.length - 1; i >= 0; i--) {
    const d = list[i];
    const a = toXY(pane, d.p1), b = d.p2 ? toXY(pane, d.p2) : null;
    if (!a) continue;
    if (TWO_POINT.has(d.type)) {
      if (Math.hypot(x - a.x, y - a.y) <= NEAR_PX) return { d, part: "p1" };
      if (b && Math.hypot(x - b.x, y - b.y) <= NEAR_PX) return { d, part: "p2" };
    }
    let on = false;
    if (d.type === "trend" && b) on = distToSeg(x, y, a, b) <= NEAR_PX;
    else if (d.type === "ray" && b) on = distToSeg(x, y, a, rayEnd(a, b, size)) <= NEAR_PX;
    else if (d.type === "hline") on = Math.abs(y - a.y) <= NEAR_PX;
    else if (d.type === "vline") on = Math.abs(x - a.x) <= NEAR_PX;
    else if (d.type === "rect" && b) {
      const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x), y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
      on = x >= x0 - NEAR_PX && x <= x1 + NEAR_PX && y >= y0 - NEAR_PX && y <= y1 + NEAR_PX;
    } else if (d.type === "fib" && b) {
      const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x, x0 + 40);
      on = x >= x0 - NEAR_PX && x <= x1 + NEAR_PX && FIB_LEVELS.some((level) => {
        const ly = pane.candles.priceToCoordinate(fibPrice(d, level));
        return ly != null && Math.abs(y - ly) <= NEAR_PX;
      });
    } else if (d.type === "text") {
      const w = Math.max(12, (d.text || "").length * 7);
      on = x >= a.x - 2 && x <= a.x + w + 4 && Math.abs(y - a.y) <= 9;
    }
    if (on) return { d, part: "body" };
  }
  return null;
}

function freezeChart(pane, on) {
  try { pane.chart.applyOptions({ handleScroll: !on, handleScale: !on }); } catch (e) {}
}
function pointerIn(pane, ev) {
  const r = pane.host.getBoundingClientRect();
  const size = paneSize(pane);
  const x = ev.clientX - r.left, y = ev.clientY - r.top;
  return { x: Math.max(0, Math.min(size.width, x)), y: Math.max(0, Math.min(size.height, y)),
           inside: x >= 0 && x <= size.width && y >= 0 && y <= size.height };
}
function newDrawingId() {
  return "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}
function addDrawing(pane, d) {
  (drawings[pane.cfg.symbol] = drawings[pane.cfg.symbol] || []).push(d);
  saveDrawings();
  selectDrawing({ pane, id: d.id });
}
function commitDraft() {
  const { pane, d } = draft;
  draft = null;
  freezeChart(pane, false);
  addDrawing(pane, d);
  setTool("cursor");
}
function selectDrawing(sel) {
  const old = selected;
  selected = sel;
  $("drawDelete").disabled = !sel;
  const d = findDrawing(sel);
  if (d) $("drawColour").value = d.color || "#58a6ff";
  if (old) redrawSymbol(old.pane.cfg.symbol);
  if (sel) redrawSymbol(sel.pane.cfg.symbol);
}
function setTool(name) {
  tool = name;
  document.querySelectorAll("#tools [data-tool]").forEach((b) =>
    b.setAttribute("aria-pressed", b.dataset.tool === name ? "true" : "false"));
  for (const p of panes) p.host.classList.toggle("drawing", name !== "cursor");
  if (draft) {
    const p = draft.pane;
    draft = null;
    freezeChart(p, false);
    p.layer.update();
  }
  if (name !== "cursor" && selected) selectDrawing(null);
}

function onPointerDown(pane, ev) {
  if (ev.button !== 0) return;
  activePane = pane;
  const m = pointerIn(pane, ev);
  if (!m.inside || !pane.bars.length) return;
  if (tool !== "cursor") {
    const pt = fromXY(pane, m.x, m.y);
    if (!pt) return;
    // Taken before the chart sees it, so placing a point never pans the chart.
    ev.preventDefault(); ev.stopPropagation();
    if (draft && draft.pane === pane) { draft.d.p2 = pt; commitDraft(); return; }
    const d = { id: newDrawingId(), type: tool, p1: pt, color: $("drawColour").value };
    if (tool === "text") {
      const text = prompt("Text for the note:");
      setTool("cursor");
      if (text && text.trim()) { d.text = text.trim().slice(0, 200); addDrawing(pane, d); }
      return;
    }
    if (!TWO_POINT.has(tool)) { addDrawing(pane, d); setTool("cursor"); return; }
    d.p2 = { ...pt };
    draft = { pane, d, x: m.x, y: m.y };
    freezeChart(pane, true);
    try { pane.host.setPointerCapture(ev.pointerId); } catch (e) {}
    pane.layer.update();
    return;
  }
  const hit = hitTest(pane, m.x, m.y);
  if (!hit) { if (selected) selectDrawing(null); return; }
  ev.preventDefault(); ev.stopPropagation();
  selectDrawing({ pane, id: hit.d.id });
  drag = { pane, d: hit.d, part: hit.part, start: fromXY(pane, m.x, m.y),
           startLx: Math.round(xToLx(pane, m.x) || 0), orig: JSON.parse(JSON.stringify(hit.d)) };
  freezeChart(pane, true);
  try { pane.host.setPointerCapture(ev.pointerId); } catch (e) {}
}

function onPointerMove(pane, ev) {
  if (draft && draft.pane === pane) {
    const m = pointerIn(pane, ev);
    const pt = fromXY(pane, m.x, m.y);
    if (pt) { draft.d.p2 = pt; pane.layer.update(); }
    return;
  }
  if (drag && drag.pane === pane) {
    const m = pointerIn(pane, ev);
    const pt = fromXY(pane, m.x, m.y);
    if (!pt || !drag.start) return;
    const d = drag.d, o = drag.orig;
    if (drag.part === "p1" || drag.part === "p2") {
      d[drag.part] = pt;
    } else {
      // The whole drawing moves by whole bars and by price.
      const dl = Math.round(xToLx(pane, m.x) || 0) - drag.startLx;
      const dp = pt.p - drag.start.p;
      for (const k of ["p1", "p2"]) {
        if (!o[k]) continue;
        const lx = timeToLogical(pane, o[k].t);
        d[k] = { t: lx == null ? o[k].t : logicalToTime(pane, lx + dl), p: o[k].p + dp };
      }
    }
    redrawSymbol(pane.cfg.symbol);
    return;
  }
  if (tool === "cursor") {
    const m = pointerIn(pane, ev);
    const hit = m.inside ? hitTest(pane, m.x, m.y) : null;
    pane.host.style.cursor = hit ? (hit.part === "body" ? "move" : "grab") : "";
  }
}

function onPointerUp(pane, ev) {
  if (draft && draft.pane === pane) {
    // Dragged out: the release is the second point. A plain click waits for another.
    const m = pointerIn(pane, ev);
    if (Math.hypot(m.x - draft.x, m.y - draft.y) > NEAR_PX) commitDraft();
    return;
  }
  if (drag && drag.pane === pane) {
    drag = null;
    freezeChart(pane, false);
    saveDrawings();
    redrawSymbol(pane.cfg.symbol);
  }
}

function wireDrawing(pane) {
  // Capture phase, so a click that places or grabs a drawing never starts a pan.
  pane.host.addEventListener("pointerdown", (ev) => onPointerDown(pane, ev), true);
  pane.host.addEventListener("pointermove", (ev) => onPointerMove(pane, ev));
  pane.host.addEventListener("pointerup", (ev) => onPointerUp(pane, ev));
  pane.host.addEventListener("pointercancel", (ev) => onPointerUp(pane, ev));
}

function deleteSelected() {
  if (!selected) return;
  const sym = selected.pane.cfg.symbol;
  drawings[sym] = listFor(sym).filter((d) => d.id !== selected.id);
  selected = null;
  $("drawDelete").disabled = true;
  saveDrawings();
  redrawSymbol(sym);
}

document.querySelectorAll("#tools [data-tool]").forEach((b) => {
  b.onclick = () => setTool(b.dataset.tool === tool ? "cursor" : b.dataset.tool);
});
$("drawDelete").onclick = deleteSelected;
$("drawClear").onclick = () => {
  const pane = activePane || panes[0];
  if (!pane) return;
  const sym = pane.cfg.symbol, n = listFor(sym).length;
  if (!n) { setStatus("no drawings on " + labelFor(sym)); return; }
  if (!confirm(`Remove all ${n} drawing${n > 1 ? "s" : ""} on ${labelFor(sym)}?`)) return;
  if (selected && selected.pane.cfg.symbol === sym) selectDrawing(null);
  delete drawings[sym];
  saveDrawings();
  redrawSymbol(sym);
};
$("drawColour").addEventListener("input", () => {
  const d = findDrawing(selected);
  if (!d) return;
  d.color = $("drawColour").value;
  saveDrawings();
  redrawSymbol(selected.pane.cfg.symbol);
});
document.addEventListener("keydown", (ev) => {
  const t = ev.target;
  if (t && (/^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName) || t.isContentEditable)) return;
  if ($("ticket").open) return;
  if (ev.key === "Escape") {
    if (draft || tool !== "cursor") setTool("cursor");
    else if (selected) selectDrawing(null);
  } else if ((ev.key === "Delete" || ev.key === "Backspace") && selected) {
    ev.preventDefault();
    deleteSelected();
  }
});

/* ---------------------------------------------------------------- time sync */
function attachSync(pane) {
  pane.syncHandler = (range) => {
    if (syncing || !range || !state.sync) return;
    syncing = true;
    for (const other of panes) {
      if (other !== pane) {
        try { other.chart.timeScale().setVisibleLogicalRange(range); } catch (e) {}
      }
    }
    syncing = false;
  };
  pane.chart.timeScale().subscribeVisibleLogicalRangeChange(pane.syncHandler);
}
function detachSync(pane) {
  if (pane.syncHandler) {
    try { pane.chart.timeScale().unsubscribeVisibleLogicalRangeChange(pane.syncHandler); }
    catch (e) {}
    pane.syncHandler = null;
  }
}

/* ------------------------------------------------------------------- layout */
function build() {
  closeSuggest();
  // Selections and half-placed drawings belong to the panes about to be replaced.
  selected = null; draft = null; drag = null; activePane = null;
  $("drawDelete").disabled = true;
  for (const p of panes) { detachSync(p); try { p.chart.remove(); } catch (e) {} }
  panes = [];
  $("grid").innerHTML = "";
  $("grid").dataset.n = String(state.count);

  while (state.panes.length < state.count) {
    state.panes.push(newPane(DEFAULTS[state.panes.length % 8], "5m"));
  }
  for (let i = 0; i < state.count; i++) panes.push(makePane(i));
  save();
  refreshAll();
  startTimer();
}

async function refreshAll() {
  setStatus("loading…");
  const started = Date.now();
  await Promise.all([...panes.map(refreshPane), loadTrades()]);
  panes.forEach(renderPaneTrade);
  const bad = panes.filter((p) => !p.errEl.hidden).length;
  setStatus(bad ? `${bad} of ${panes.length} panes failed` : `${panes.length} charts · ${Date.now() - started}ms`, bad > 0);
}

function startTimer() {
  if (timer) { clearInterval(timer); timer = null; }
  if (state.refresh > 0) timer = setInterval(refreshAll, state.refresh);
}

/* -------------------------------------------------------------------- boot */
$("count").onchange = () => { state.count = Number($("count").value); save(); build(); };
$("source").onchange = () => {
  state.source = $("source").value; save();
  known.clear();
  loadSymbols().then(() => { panes.forEach(showSymbol); refreshAll(); });
};
$("refresh").onchange = () => { state.refresh = Number($("refresh").value); save(); startTimer(); };
$("sync").onchange = () => {
  state.sync = $("sync").checked; save();
  panes.forEach((p) => { detachSync(p); if (state.sync) attachSync(p); });
};
$("reset").onclick = () => {
  if (!confirm("Forget the saved layout, pane selections and colours?")) return;
  localStorage.removeItem(STORE);
  const indicators = CATALOG.filter((s) => s.default).map((s) => s.id);
  state = load();
  state.indicators = indicators;
  applyControls();
  build();
};
// Close the indicator picker when clicking anywhere else, like a menu would.
document.addEventListener("click", (ev) => {
  const box = $("indBox");
  if (box.open && !box.contains(ev.target)) box.open = false;
});

function applyControls() {
  $("count").value = String(state.count);
  $("refresh").value = String(state.refresh);
  $("sync").checked = !!state.sync;
  renderIndicatorPicker();
}

function colourInput(key, value, label) {
  return `<input type="color" class="pick" data-colour="${esc(key)}" value="${esc(value)}"
            aria-label="${esc(label)}" title="${esc(label)}" />`;
}

/* An indicator parameter as set on this page, else the catalog default. */
function paramValue(spec, key) {
  const p = (spec.params || []).find((x) => x.key === key);
  const given = ((state.indParams || {})[spec.id] || {})[key];
  return given != null && given !== "" ? given : (p ? p.default : null);
}
function indLabel(spec) {
  if (spec.id === "zema_fast" || spec.id === "zema_slow") {
    return `ZEMA(${paramValue(spec, "period")}) zero-lag EMA`;
  }
  if (spec.id === "st_tf1" || spec.id === "st_tf2") {
    const tf = paramValue(spec, "tf");
    return `Supertrend ${tf === "chart" ? "(chart timeframe)" : tf} ` +
      `(${paramValue(spec, "period")}, ${paramValue(spec, "factor")})`;
  }
  return spec.label;
}
function paramRow(spec) {
  const params = spec.params || [];
  if (!params.length) return "";
  return `<div class="pp">${params.map((p) => {
    const v = paramValue(spec, p.key);
    const id = `par-${spec.id}-${p.key}`;
    const ref = `${esc(spec.id)}.${esc(p.key)}`;
    if (p.type === "tf") {
      const opts = [["chart", "chart's"], ...TIMEFRAMES.map((t) => [t, t])];
      return `<label for="${id}">${esc(p.label)}</label><select id="${id}" data-param="${ref}">
        ${opts.map(([val, text]) => `<option value="${esc(val)}" ${String(v) === val ? "selected" : ""}>${esc(text)}</option>`).join("")}
        </select>`;
    }
    return `<label for="${id}">${esc(p.label)}</label><input id="${id}" type="number" data-param="${ref}"
      min="${p.min}" max="${p.max}" step="${p.step || 1}" value="${esc(v)}" inputmode="decimal" />`;
  }).join("")}</div>`;
}

function renderIndicatorPicker() {
  const byPane = { 0: [], 1: [], 2: [] };
  for (const spec of CATALOG) (byPane[spec.pane] ||= []).push(spec);
  const heads = { 0: "On the price chart", 1: "RSI pane", 2: "ADX pane" };
  const cc = candleColours();
  let html = `<div class="sep">Candles &amp; volume</div>
    <div class="indrow">${colourInput("candles:up", cc.up, "Up candle colour")}<span>Up</span>
      ${colourInput("candles:down", cc.down, "Down candle colour")}<span>Down</span></div>`;
  for (const key of Object.keys(byPane)) {
    if (!byPane[key].length) continue;
    html += `<div class="sep">${esc(heads[key] || "Pane " + key)}</div>`;
    html += byPane[key].map((spec) => `
      <div class="indrow">
        <input type="checkbox" id="ind-${esc(spec.id)}" data-ind="${esc(spec.id)}"
               ${state.indicators.includes(spec.id) ? "checked" : ""} />
        ${spec.color_down
          ? colourInput(spec.id, colourFor(spec, "up"), indLabel(spec) + " — uptrend colour") +
            colourInput(spec.id + ":down", colourFor(spec, "down"), indLabel(spec) + " — downtrend colour")
          : colourInput(spec.id, colourFor(spec), indLabel(spec) + " colour")}
        <label for="ind-${esc(spec.id)}" id="indl-${esc(spec.id)}">${esc(indLabel(spec))}${spec.color_down
          ? ' <span class="mut">up / down</span>' : ""}</label>
      </div>${paramRow(spec)}`).join("");
  }
  html += `<div class="foot"><button type="button" id="resetColours">Reset colours</button>
    <button type="button" id="resetParams" title="ZEMA 50 / 200; Supertrend chart timeframe and 15m, ATR 10, factor 3">Reset parameters</button></div>`;
  $("indList").innerHTML = html;

  // Parameters refetch, since the server computes the lines.
  $("indList").querySelectorAll("[data-param]").forEach((input) => {
    input.onchange = () => {
      const [id, key] = input.dataset.param.split(".");
      const spec = CATALOG.find((s) => s.id === id);
      const p = spec && (spec.params || []).find((x) => x.key === key);
      if (!p) return;
      let value = input.value.trim();
      if (p.type !== "tf") {
        const num = Number(value);
        const ok = value !== "" && Number.isFinite(num) && num >= p.min && num <= p.max &&
          (p.type !== "int" || Number.isInteger(num));
        input.classList.toggle("bad", !ok);
        if (!ok) { input.title = `${p.label}: ${p.min} to ${p.max}`; return; }
        value = num;
      }
      state.indParams[id] = { ...(state.indParams[id] || {}), [key]: value };
      save();
      const label = $("indl-" + id);
      if (label) label.firstChild.textContent = indLabel(spec);
      updatePickerSummary();
      refreshAll();
    };
  });
  $("resetParams").onclick = () => {
    state.indParams = {};
    save();
    renderIndicatorPicker();
    refreshAll();
  };

  $("indList").querySelectorAll("[data-ind]").forEach((box) => {
    box.onchange = () => {
      const id = box.dataset.ind;
      state.indicators = box.checked
        ? [...new Set([...state.indicators, id])]
        : state.indicators.filter((x) => x !== id);
      // Keep the catalog order so pane assignment stays predictable.
      state.indicators = CATALOG.map((s) => s.id).filter((x) => state.indicators.includes(x));
      save();
      panes.forEach(buildIndicatorSeries);
      updatePickerSummary();
      refreshAll();
    };
  });
  // Colour changes only need the series restyled, not refetched.
  $("indList").querySelectorAll("[data-colour]").forEach((input) => {
    input.oninput = () => {
      state.colours[input.dataset.colour] = input.value;
      save();
      applyColours();
    };
  });
  $("resetColours").onclick = () => {
    state.colours = {};
    save();
    renderIndicatorPicker();
    applyColours();
  };
  updatePickerSummary();
}

function updatePickerSummary() {
  const on = state.indicators.length;
  $("indBox").querySelector("summary").textContent =
    on ? `Indicators (${on}) & colours` : "Indicators & colours";
}

/* Restyle live series in place. Volume bars carry their colour per bar, so they are
   repainted from the bars already on screen rather than refetched. */
function applyColours() {
  const opts = candleOptions();
  const theme = chartThemeOptions();
  for (const pane of panes) {
    try { pane.chart.applyOptions(theme); } catch (e) {}
    try { pane.candles.applyOptions(opts); } catch (e) {}
    if (pane.bars.length) {
      try { pane.volume.setData(pane.bars.map(volumePoint)); } catch (e) {}
    }
    for (const spec of CATALOG) {
      const list = pane.ind[spec.id];
      if (!list) continue;
      try {
        list[0].applyOptions({ color: colourFor(spec, "up") });
        if (list[1]) list[1].applyOptions({ color: colourFor(spec, "down") });
      } catch (e) {}
    }
  }
}
window.addEventListener("matheran-theme-change", applyColours);

async function loadSymbols() {
  try {
    const d = await api("/api/charts/symbols?limit=300&source=" + encodeURIComponent(state.source));
    for (const s of d.symbols || []) known.set(s.id, s);
  } catch (e) {
    setStatus("symbol list unavailable: " + e.message, true);
  }
}

async function boot() {
  if (!LWC || !LWC.createChart) {
    setStatus("Lightweight Charts failed to load from /static", true);
    return;
  }
  try {
    const d = await api("/api/charts/sources");
    const list = d.sources || [];
    $("source").innerHTML = list.map((s) =>
      `<option value="${esc(s.name)}">${esc(s.label)}</option>`).join("");
    if (!list.some((s) => s.name === state.source) && list.length) state.source = list[0].name;
    $("source").value = state.source;
    CATALOG = d.indicators || [];
    if (Array.isArray(d.timeframe_info) && d.timeframe_info.length) {
      TIMEFRAMES = d.timeframe_info.map((t) => t.id);
      TF_MIN = Object.fromEntries(d.timeframe_info.map((t) => [t.id, t.minutes]));
    }
    for (const p of state.panes) if (p) p.timeframe = normTf(p.timeframe) || "5m";
    if (!state.indParams || typeof state.indParams !== "object") state.indParams = {};
    // First visit, or a saved list from before the catalog existed.
    if (!Array.isArray(state.indicators)) state.indicators = d.default_indicators || [];
    const ids = new Set(CATALOG.map((s) => s.id));
    state.indicators = state.indicators.filter((id) => ids.has(id));
    if (!state.colours || typeof state.colours !== "object") state.colours = {};
    save();
  } catch (e) {
    setStatus(e.message + (String(e.message).indexOf("X-API-Key") >= 0
      ? "  →  open the console first and enter the dashboard password" : ""), true);
    return;
  }
  applyUrlRequest();
  applyControls();
  await Promise.all([loadSymbols(), loadStatus()]);
  build();
}
boot();
</script>
</body>
</html>
"""
