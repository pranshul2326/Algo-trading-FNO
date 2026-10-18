"""Basket combo screen: four charts on one page, as the TradingView combo script draws them.

    +----------------------+----------------------+
    |  underlying spot     |  call legs           |
    +----------------------+----------------------+
    |  combined premium    |  put legs            |
    |  + Advanced VWAP / EMA / ST   |                      |
    +----------------------+----------------------+

The arithmetic lives in combo.py; this page only draws what /api/combo returns.
Plain HTML and CSS with the vendored Lightweight Charts, like the charts page.
"""

COMBO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="/static/ui-theme.js"></script>
<title>Matheran basket combo</title>
<script src="/static/lightweight-charts.standalone.production.js"></script>
<style>
  :root {
    --bg:#0f1216; --panel:#171c22; --panel2:#1c2229; --line:#2a323c; --text:#e6edf3;
    --muted:#9aa7b4; --up:#3fb950; --down:#f85149; --accent:#58a6ff; --gap:8px;
  }
  * { box-sizing:border-box; }
  html,body { height:100%; }
  body { margin:0; background:var(--bg); color:var(--text); overflow:hidden;
    font:13px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }

  header { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap;
    padding:7px 14px 8px; border-bottom:1px solid var(--line); }
  h1 { font-size:14px; margin:0 6px 3px 0; font-weight:650; align-self:center; }
  h1 a { color:var(--muted); text-decoration:none; font-weight:500; margin-left:10px; font-size:13px; }
  h1 a:hover { color:var(--accent); }
  label.f { display:flex; flex-direction:column; gap:3px; font-size:11px; color:var(--muted); }
  label.inline { display:flex; align-items:center; gap:6px; font-size:12.5px; color:var(--text);
    align-self:center; }
  select,input,button { background:#0d1117; color:var(--text); border:1px solid var(--line);
    border-radius:6px; padding:4px 7px; font:inherit; font-size:12.5px; }
  button { background:#21262d; cursor:pointer; }
  button:hover { background:#2d333b; }
  :focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
  .grow { margin-left:auto; }
  .pill { font-size:11.5px; color:var(--muted); border:1px solid var(--line); border-radius:999px;
    padding:2px 9px; align-self:center; max-width:420px; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; }
  .pill.bad { color:#ffb3b3; border-color:#7d232b; background:#4a1218; }

  details.drop { position:relative; align-self:flex-end; }
  details.drop > summary { cursor:pointer; list-style:none; background:#21262d;
    border:1px solid var(--line); border-radius:6px; padding:4px 10px; font-size:12.5px; }
  details.drop > summary::-webkit-details-marker { display:none; }
  details.drop > summary::after { content:" ▾"; color:var(--muted); }
  details.drop[open] > summary { border-color:var(--accent); }
  .dropbody { position:absolute; z-index:30; top:calc(100% + 5px); left:0; min-width:250px;
    background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:9px 11px;
    box-shadow:0 8px 26px #0008; display:grid; gap:7px; }
  .dropbody .indrow { display:flex; align-items:center; gap:8px; font-size:12.5px; }
  .dropbody input[type=number] { width:64px; }
  .swatch { display:inline-block; width:11px; height:11px; border-radius:2px; }

  main { height:calc(100vh - 58px); padding:var(--gap); }
  /* Spot top left, combo under it; calls top right, puts under them. */
  .grid { display:grid; gap:var(--gap); height:100%; grid-template-columns:1fr 1fr;
    grid-template-rows:1fr 1fr; grid-template-areas:"spot call" "combo put"; }
  #pSpot { grid-area:spot; } #pCombo { grid-area:combo; }
  #pCall { grid-area:call; } #pPut { grid-area:put; }

  .pane { background:var(--panel); border:1px solid var(--line); border-radius:8px;
    display:flex; flex-direction:column; min-height:0; min-width:0; overflow:hidden; }
  /* Narrow screens: one column in reading order - spot, combo, calls, puts. Placed
     after .pane so its height wins. */
  @media (max-width:900px) {
    body { overflow:auto; }
    main { height:auto; }
    .grid { grid-template-columns:1fr; grid-template-rows:none;
      grid-template-areas:"spot" "combo" "call" "put"; }
    .grid .pane { min-height:340px; }
  }
  .bar { display:flex; gap:8px; align-items:center; padding:5px 9px; min-height:31px;
    border-bottom:1px solid var(--line); }
  .bar h2 { font-size:12.5px; margin:0; font-weight:650; white-space:nowrap; }
  .bar .legs { color:var(--muted); font-size:11.5px; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; min-width:0; }
  .bar .last { margin-left:auto; font-variant-numeric:tabular-nums; font-size:12.5px;
    white-space:nowrap; }
  .chart { flex:1; min-height:0; position:relative; }
  .chart .empty { position:absolute; inset:0; display:grid; place-items:center; color:var(--muted);
    font-size:12px; pointer-events:none; text-align:center; padding:0 24px; z-index:4; }
  .up { color:var(--up); } .down { color:var(--down); } .mut { color:var(--muted); }
  [hidden] { display:none !important; }
  .sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0);
    white-space:nowrap; }

  /* The script's info table, over the combo chart. */
  .tbl { position:absolute; top:6px; left:6px; z-index:5; background:#0f1216e8;
    border:1px solid var(--line); border-radius:7px; max-height:calc(100% - 44px); max-width:calc(100% - 80px);
    overflow:auto; font-size:11.5px; }
  .tbl table { border-collapse:collapse; font-variant-numeric:tabular-nums; }
  .tbl th, .tbl td { padding:2px 8px; text-align:right; white-space:nowrap;
    border-bottom:1px solid #222a33; }
  .tbl th { color:#fff; background:#1f3a5f; font-weight:600; }
  .tbl td.l, .tbl th.l { text-align:left; }
  .tbl tr.calls td { background:#0f2f2c; }
  .tbl tr.puts td { background:#2a1633; }
  .tbl tr.total td { background:#2a2f36; font-weight:650; }

  body { display:flex; flex-direction:column; }
  main { flex:1; min-height:0; height:auto; }
  @media (max-width:900px) {
    header { padding:7px 8px; align-items:center; }
    header h1 { flex:1 1 100%; }
    header .grow { display:none; }
    header label.f, header details.drop { flex:1 1 112px; min-width:0; }
    header select, header details.drop > summary { width:100%; max-width:100%; }
    header .pill { flex:1 1 100%; max-width:100%; }
    main { width:100%; padding:6px; }
    .dropbody { position:fixed; top:8px; left:8px; right:8px; width:auto; min-width:0;
      max-height:calc(100dvh - 16px); overflow:auto; }
    .tbl { max-width:calc(100% - 12px); width:calc(100% - 12px); }
    .bar { flex-wrap:wrap; }
    .bar .last { margin-left:auto; }
  }
</style>
<link rel="stylesheet" href="/static/ui-theme.css" />
</head>
<body>
<header>
  <h1>Basket combo <a href="/#baskets">← console</a> <a href="/charts">charts ↗</a>
    <a href="/chain">option chain ↗</a></h1>
  <label class="f" for="basket">Basket <select id="basket"><option value="">loading…</option></select></label>
  <label class="f" for="tf">Timeframe <select id="tf"></select></label>
  <label class="f" for="range" title="How the combo's high and low are inferred from its legs">Bar range
    <select id="range">
      <option value="spot">Spot linked</option>
      <option value="body">Body only</option>
      <option value="wicks">Sum leg wicks</option>
    </select></label>
  <label class="f" for="comboStyle">Combo
    <select id="comboStyle"><option value="candles">Candles</option><option value="line">Line</option></select></label>
  <label class="f" for="cpStyle">Call / put
    <select id="cpStyle"><option value="line">Line</option><option value="candles">Candles</option></select></label>
  <label class="f" for="cp" title="Absolute = always positive (what the spread costs); Net keeps the sign, so a credit shows negative">Call/put price
    <select id="cp"><option value="abs">Absolute</option><option value="net">Net (signed)</option></select></label>
  <details id="indBox" class="drop">
    <summary>Indicators</summary>
    <div class="dropbody" id="indList">
      <div class="indrow"><input type="checkbox" id="iVwap" /><span class="swatch" style="background:#f59e0b"></span>
        <label for="iVwap">Advanced VWAP (session)</label></div>
      <div class="indrow"><input type="checkbox" id="iEma1" /><span class="swatch" style="background:#22d3ee"></span>
        <label for="iEma1">EMA 1</label>
        <input type="number" id="iEma1Len" min="1" max="500" step="1" aria-label="EMA 1 length" /></div>
      <div class="indrow"><input type="checkbox" id="iEma2" /><span class="swatch" style="background:#e879f9"></span>
        <label for="iEma2">EMA 2</label>
        <input type="number" id="iEma2Len" min="1" max="500" step="1" aria-label="EMA 2 length" /></div>
      <div class="indrow"><input type="checkbox" id="iSt" /><span class="swatch" style="background:#3fb950"></span>
        <label for="iSt">Supertrend</label></div>
      <div class="indrow" style="padding-left:24px">
        <label for="iStF">Factor</label><input type="number" id="iStF" min="0.1" max="50" step="0.1" />
        <label for="iStAtr">ATR</label><input type="number" id="iStAtr" min="1" max="500" step="1" /></div>
    </div>
  </details>
  <label class="f" for="pl">P/L
    <select id="pl"><option value="points">Points</option><option value="rupees">Rupees</option></select></label>
  <label class="f" for="refresh">Refresh
    <select id="refresh"><option value="0">off</option><option value="5000">5s</option>
      <option value="15000">15s</option><option value="60000">60s</option></select></label>
  <label class="inline" for="sync"><input type="checkbox" id="sync" /> Sync time</label>
  <label class="inline" for="showTbl"><input type="checkbox" id="showTbl" /> Table</label>
  <label class="theme-picker" for="themeSelect">Theme
    <select id="themeSelect" data-theme-select><option value="night">Night</option><option value="light">Light</option></select>
  </label>
  <div class="grow"></div>
  <span id="status" class="pill" role="status" aria-live="polite">…</span>
</header>

<main><div class="grid">
  <section class="pane" id="pSpot" aria-labelledby="tSpot">
    <div class="bar"><h2 id="tSpot">Spot</h2><span class="legs" id="sSpot"></span>
      <span class="last mut" id="lSpot">—</span></div>
    <div class="chart" id="cSpot"><div class="empty">loading…</div></div>
  </section>
  <section class="pane" id="pCombo" aria-labelledby="tCombo">
    <div class="bar"><h2 id="tCombo">Combo</h2><span class="legs" id="sCombo"></span>
      <span class="last mut" id="lCombo">—</span></div>
    <div class="chart" id="cCombo"><div class="empty">loading…</div>
      <div class="tbl" id="tbl" hidden></div></div>
  </section>
  <section class="pane" id="pCall" aria-labelledby="tCall">
    <div class="bar"><h2 id="tCall">Calls</h2><span class="legs" id="sCall"></span>
      <span class="last mut" id="lCall">—</span></div>
    <div class="chart" id="cCall"><div class="empty">loading…</div></div>
  </section>
  <section class="pane" id="pPut" aria-labelledby="tPut">
    <div class="bar"><h2 id="tPut">Puts</h2><span class="legs" id="sPut"></span>
      <span class="last mut" id="lPut">—</span></div>
    <div class="chart" id="cPut"><div class="empty">loading…</div></div>
  </section>
</div></main>

<script>
"use strict";
const LWC = window.LightweightCharts;
const $ = (id) => document.getElementById(id);
const KEY = sessionStorage.getItem("mthKey") || "";
const STORE = "matheranCombo.v1";
const TIMEFRAMES = ["1m", "3m", "5m", "9m", "15m", "30m", "1h", "2h", "1D", "1W", "1M"];
const TF_ALIAS = { "60m": "1h", "120m": "2h", "1d": "1D", "1w": "1W" };
const normTf = (tf) => (TIMEFRAMES.includes(tf) ? tf : (TF_ALIAS[tf] || null));
// The script's default colours, where it names one.
const C = {
  up: "#3fb950", down: "#f85149", comboLine: "#f2cc60",
  callLine: "#22d3ee", callUp: "#14b8a6", callDown: "#be123c",
  putLine: "#e879f9", putUp: "#a855f7", putDown: "#f97316",
  vwap: "#f59e0b", ema1: "#22d3ee", ema2: "#e879f9", stUp: "#3fb950", stDown: "#f85149",
  spotVwap: "#f2cc60", spotEma: "#58a6ff",
};

let state = load();
let ADHOC = "";          // unsaved legs handed over by the option chain
let LAST = null;         // last /api/combo payload, for redraws that need no refetch
let timer = null;
let seq = 0;
let syncing = false;

function load() {
  const base = {
    basket: "", tf: "5m", range: "spot", comboStyle: "candles", cpStyle: "line", cp: "abs",
    pl: "points", refresh: 5000, sync: true, table: true,
    ind: { vwap: true, ema1: true, ema1Len: 9, ema2: true, ema2Len: 21, st: true, stF: 3, stAtr: 10 },
  };
  try {
    const s = JSON.parse(localStorage.getItem(STORE) || "null");
    if (s && typeof s === "object") {
      const out = { ...base, ...s, ind: { ...base.ind, ...(s.ind || {}) } };
      out.tf = normTf(out.tf) || "5m";
      return out;
    }
  } catch (e) { /* defaults */ }
  return base;
}
function save() { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }

async function api(path) {
  const h = { "Accept": "application/json" };
  if (KEY) h["X-API-Key"] = KEY;
  const res = await fetch(path, { headers: h });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = { detail: text }; }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d
      : Array.isArray(d) ? d.map((x) => (x && x.msg) || JSON.stringify(x)).join("; ")
      : res.statusText);
  }
  return body;
}
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
const fmt = (v) => (v == null || Number.isNaN(Number(v))) ? "—" : Number(v).toFixed(2);
function setStatus(text, bad) {
  $("status").textContent = text;
  $("status").title = text;
  $("status").className = "pill" + (bad ? " bad" : "");
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

/* Bar times are UNIX seconds, which the library labels in UTC; every label is shown
   in IST instead, as on the charts page. */
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
  if (type === 0) return String(p.y);
  if (type === 1) return MONTHS[p.mo];
  if (type === 2) return `${p.d} ${MONTHS[p.mo]}`;
  return `${pad2(p.h)}:${pad2(p.mi)}`;
}
function istCrosshair(time) {
  const p = istParts(time);
  return `${p.d} ${MONTHS[p.mo]} ${p.y}  ${pad2(p.h)}:${pad2(p.mi)} IST`;
}

/* -------------------------------------------------------------- the panes */
const P = {};
function makePane(key, cap) {
  const host = $("c" + cap);
  const theme = chartThemeOptions();
  const chart = LWC.createChart(host, {
    layout: theme.layout,
    grid: theme.grid,
    rightPriceScale: { ...theme.rightPriceScale, scaleMargins: { top: 0.08, bottom: 0.08 } },
    localization: { timeFormatter: istCrosshair },
    timeScale: { ...theme.timeScale, timeVisible: true, secondsVisible: false, rightOffset: 3,
                 tickMarkFormatter: istTick },
    crosshair: { mode: LWC.CrosshairMode.Normal },
    autoSize: true,
  });
  P[key] = {
    key, chart, main: null, style: "", lines: {}, lastTime: 0, loaded: false, hasData: false,
    emptyEl: host.querySelector(".empty"), lastEl: $("l" + cap), subEl: $("s" + cap), titleEl: $("t" + cap),
  };
  chart.timeScale().subscribeVisibleTimeRangeChange((range) => syncFrom(P[key], range));
}
window.addEventListener("matheran-theme-change", () => {
  const theme = chartThemeOptions();
  for (const pane of Object.values(P)) {
    try { pane.chart.applyOptions(theme); } catch (e) {}
  }
});

function ensureMain(p, style, colours) {
  if (p.main && p.style === style) return;
  if (p.main) { try { p.chart.removeSeries(p.main); } catch (e) {} }
  p.main = style === "line"
    ? p.chart.addSeries(LWC.LineSeries, { color: colours.line, lineWidth: 2 })
    : p.chart.addSeries(LWC.CandlestickSeries, {
        upColor: colours.up, downColor: colours.down, wickUpColor: colours.up,
        wickDownColor: colours.down, borderVisible: false });
  p.style = style;
  p.loaded = false;
  p.lastTime = 0;
}

const toPoint = (style, b) => style === "line" ? { time: b.time, value: b.close }
  : { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close };

/* First load draws everything; a refresh only pushes bars from the newest one on,
   so zoom and pan survive, as on the charts page. */
function setBars(p, bars, emptyText) {
  if (!bars || !bars.length) {
    if (p.main) p.main.setData([]);
    p.loaded = false;
    p.hasData = false;
    p.emptyEl.textContent = emptyText;
    p.emptyEl.hidden = false;
    p.lastEl.textContent = "—";
    p.lastEl.className = "last mut";
    return;
  }
  p.emptyEl.hidden = true;
  if (!p.loaded) {
    p.main.setData(bars.map((b) => toPoint(p.style, b)));
    p.chart.timeScale().fitContent();
    p.loaded = true;
  } else {
    for (const b of bars) {
      if (b.time < p.lastTime) continue;
      try { p.main.update(toPoint(p.style, b)); } catch (e) {}
    }
  }
  p.hasData = true;
  p.lastTime = bars[bars.length - 1].time;
  const last = bars[bars.length - 1], prev = bars.length > 1 ? bars[bars.length - 2] : last;
  const chg = last.close - prev.close;
  p.lastEl.className = "last " + (chg > 0 ? "up" : chg < 0 ? "down" : "mut");
  p.lastEl.textContent = `${fmt(last.close)}  ${chg >= 0 ? "+" : ""}${fmt(chg)}`;
}

function lineOn(p, id, colour, width) {
  if (!p.lines[id]) {
    p.lines[id] = p.chart.addSeries(LWC.LineSeries, {
      color: colour, lineWidth: width || 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false });
  }
  return p.lines[id];
}
function lineOff(p, id) {
  if (!p.lines[id]) return;
  try { p.chart.removeSeries(p.lines[id]); } catch (e) {}
  delete p.lines[id];
}
function setLine(p, id, points, colour, on, width) {
  if (!on || !points || !points.length) { lineOff(p, id); return; }
  lineOn(p, id, colour, width).setData(points.map((x) => ({ time: x.time, value: x.value })));
}
/* Supertrend in two series, one per trend side; a bare {time} breaks the line at a flip. */
function setTrend(p, id, points, on) {
  if (!on || !points || !points.length) { lineOff(p, id + ":up"); lineOff(p, id + ":dn"); return; }
  lineOn(p, id + ":up", C.stUp, 2).setData(points.map((x) =>
    x.trend === -1 ? { time: x.time, value: x.value } : { time: x.time }));
  lineOn(p, id + ":dn", C.stDown, 2).setData(points.map((x) =>
    x.trend === -1 ? { time: x.time } : { time: x.time, value: x.value }));
}

/* Keep the four time axes together, by time rather than bar index: the legs and the
   spot need not have the same number of bars. */
function syncFrom(src, range) {
  if (syncing || !state.sync || !range) return;
  syncing = true;
  for (const p of Object.values(P)) {
    if (p === src || !p.hasData) continue;
    try { p.chart.timeScale().setVisibleRange(range); } catch (e) {}
  }
  syncing = false;
}

/* ------------------------------------------------------------------ data */
function legText(l) {
  const strike = l.strike != null ? Number(l.strike).toString() + " " : "";
  return `${l.qty_text} ${strike}${l.option_type || l.label}`;
}

function comboQuery() {
  const q = new URLSearchParams({
    timeframe: state.tf, range: state.range, cp: state.cp,
    ema1: String(state.ind.ema1Len), ema2: String(state.ind.ema2Len),
    st_factor: String(state.ind.stF), st_atr: String(state.ind.stAtr),
  });
  if (ADHOC) q.set("legs", ADHOC);
  else if (state.basket) q.set("basket", state.basket);
  else return null;
  return q;
}

function resetPanes() {
  for (const p of Object.values(P)) { p.loaded = false; p.lastTime = 0; }
}

async function refresh(full) {
  const q = comboQuery();
  if (!q) {
    setStatus("no basket selected", true);
    for (const p of Object.values(P)) setBars(p, [], "Save a basket on the console's Baskets tab or from the option chain, then pick it above.");
    return;
  }
  const mine = ++seq;
  if (full) resetPanes();
  const started = Date.now();
  if (full) setStatus("loading…");
  try {
    const d = await api("/api/combo?" + q.toString());
    if (mine !== seq) return;
    LAST = d;
    render(d);
    const total = (d.table && d.table.legs.length) || 0;
    setStatus(`${d.name} · ${d.legs_with_data}/${total} legs with data · ${d.timeframe} · ` +
      `${Date.now() - started}ms` + (d.errors.length ? ` · ${d.errors.join("; ")}` : ""),
      d.errors.length > 0);
  } catch (e) {
    if (mine !== seq) return;
    setStatus(e.message + (String(e.message).indexOf("X-API-Key") >= 0
      ? "  →  open the console first and enter the dashboard password" : ""), true);
    for (const p of Object.values(P)) if (!p.loaded) setBars(p, [], e.message);
  }
}

function render(d) {
  const legs = (d.table && d.table.legs) || [];

  // Underlying spot, with the strategy's Advanced VWAP, EMA and Supertrend.
  const sp = P.spot, spot = d.spot || {};
  ensureMain(sp, "candles", { up: C.up, down: C.down, line: C.comboLine });
  sp.titleEl.textContent = (spot.symbol || "").replace(/^idx:/, "").replace(/^eq:NSE:/, "") + " spot";
  sp.subEl.textContent = spot.note || "";
  setBars(sp, spot.bars, spot.error || "no data for the underlying");
  const si = spot.indicators || {};
  setLine(sp, "vwap", si.vwap, C.spotVwap, true, 1);
  setLine(sp, "ema", si.ema_price, C.spotEma, true, 1);
  setTrend(sp, "st", si.supertrend, true);

  // Combined premium, with the script's Advanced VWAP, two EMAs and Supertrend.
  const cb = P.combo, ind = state.ind;
  ensureMain(cb, state.comboStyle, { up: C.up, down: C.down, line: C.comboLine });
  cb.titleEl.textContent = "Combo premium (points) · " + d.name;
  cb.titleEl.title = "Sum or difference of the leg prices; legs in equal lots count once each, " +
    "never price × lot size";
  cb.subEl.textContent = legs.map(legText).join("  ·  ");
  cb.subEl.title = cb.subEl.textContent;
  setBars(cb, d.combo.bars, d.errors.length ? d.errors.join("; ") : "these legs have no data yet");
  const ci = d.combo.indicators || {};
  setLine(cb, "vwap", ci.vwap, C.vwap, ind.vwap, 2);
  setLine(cb, "ema1", ci.ema1, C.ema1, ind.ema1, 1);
  setLine(cb, "ema2", ci.ema2, C.ema2, ind.ema2, 1);
  setTrend(cb, "st", ci.supertrend, ind.st);
  renderTable(d.table);

  // Call legs and put legs, each on its own scale, so no rescaling is needed.
  for (const [key, side, word, cols] of [
    ["call", "CE", "Calls", { up: C.callUp, down: C.callDown, line: C.callLine }],
    ["put", "PE", "Puts", { up: C.putUp, down: C.putDown, line: C.putLine }],
  ]) {
    const p = P[key];
    ensureMain(p, state.cpStyle, cols);
    const mine = legs.filter((l) => l.option_type === side);
    p.titleEl.textContent = word + (state.cp === "net" ? " (net)" : "");
    p.subEl.textContent = mine.map(legText).join("  ·  ");
    p.subEl.title = p.subEl.textContent;
    setBars(p, d[key] && d[key].bars, mine.length ? "no data for these legs yet"
                                                  : `no ${word.toLowerCase()} in this basket`);
  }
}

function renderTable(t) {
  const box = $("tbl");
  if (!state.table || !t || !t.legs.length) { box.hidden = true; return; }
  const pts = state.pl === "points";
  const num = (v) => v == null ? "—" : Number(v).toFixed(2);
  const tone = (v) => v == null ? "" : v >= 0 ? "up" : "down";
  const lots = (v) => (v > 0 ? "+" : "") + Number(v).toString();
  const rows = t.legs.map((l) => {
    const pl = pts ? l.pl_points : l.pl_rupees;
    return `<tr><td class="l">${l.strike != null ? esc(Number(l.strike).toString()) : esc(l.label)}</td>
      <td class="l">${esc(l.option_type || "—")}</td><td>${esc(l.qty_text)}</td>
      <td>${num(l.entry)}</td>
      <td>${l.has_data ? num(l.ltp) : `<span class="down" title="${esc(l.error)}">NO DATA</span>`}</td>
      <td class="${tone(pl)}">${num(pl)}</td></tr>`;
  });
  const group = (g, cls, label) => {
    const pl = pts ? g.pl_points : g.pl_rupees;
    return `<tr class="${cls}"><td class="l">${g.name}</td><td class="l">${label}</td>
      <td>${g.name === "TOTAL" ? g.legs + "L" : g.legs ? lots(g.lots_net) : "—"}</td>
      <td>${num(pts ? g.entry_points : g.entry_rupees)}</td>
      <td>${num(pts ? g.value_points : g.value_rupees)}</td>
      <td class="${tone(pl)}">${num(pl)}</td></tr>`;
  };
  box.innerHTML = `<table><caption class="sr">Combo legs, entries and P&amp;L</caption>
    <thead><tr><th class="l" scope="col">Strike</th><th class="l" scope="col">C/P</th>
      <th scope="col">Qty</th><th scope="col">Entry</th><th scope="col">LTP</th>
      <th scope="col">P/L ${pts ? "pts" : "₹"}</th></tr></thead>
    <tbody>${rows.join("")}${group(t.calls, "calls", "Call")}${group(t.puts, "puts", "Put")}
      ${group(t.total, "total", pts ? "Pts" : "Rs")}</tbody></table>`;
  box.hidden = false;
}

/* --------------------------------------------------------------- controls */
function startTimer() {
  if (timer) { clearInterval(timer); timer = null; }
  if (state.refresh > 0) {
    timer = setInterval(() => { if (!document.hidden) refresh(false); }, state.refresh);
  }
}

function applyControls() {
  $("tf").innerHTML = TIMEFRAMES.map((t) => `<option value="${t}">${t}</option>`).join("");
  $("tf").value = state.tf;
  $("range").value = state.range;
  $("comboStyle").value = state.comboStyle;
  $("cpStyle").value = state.cpStyle;
  $("cp").value = state.cp;
  $("pl").value = state.pl;
  $("refresh").value = String(state.refresh);
  $("sync").checked = !!state.sync;
  $("showTbl").checked = !!state.table;
  const i = state.ind;
  $("iVwap").checked = !!i.vwap; $("iEma1").checked = !!i.ema1; $("iEma2").checked = !!i.ema2;
  $("iSt").checked = !!i.st;
  $("iEma1Len").value = i.ema1Len; $("iEma2Len").value = i.ema2Len;
  $("iStF").value = i.stF; $("iStAtr").value = i.stAtr;
}

// A change of data needs a refetch; a change of what is drawn only needs a redraw.
const refetch = () => { save(); refresh(true); };
const redraw = () => { save(); if (LAST) render(LAST); };
$("tf").onchange = () => { state.tf = $("tf").value; refetch(); };
$("range").onchange = () => { state.range = $("range").value; refetch(); };
$("cp").onchange = () => { state.cp = $("cp").value; refetch(); };
$("comboStyle").onchange = () => { state.comboStyle = $("comboStyle").value; resetPanes(); redraw(); };
$("cpStyle").onchange = () => { state.cpStyle = $("cpStyle").value; resetPanes(); redraw(); };
$("pl").onchange = () => { state.pl = $("pl").value; redraw(); };
$("showTbl").onchange = () => { state.table = $("showTbl").checked; redraw(); };
$("sync").onchange = () => { state.sync = $("sync").checked; save(); };
$("refresh").onchange = () => { state.refresh = Number($("refresh").value); save(); startTimer(); };
for (const [id, key] of [["iVwap", "vwap"], ["iEma1", "ema1"], ["iEma2", "ema2"], ["iSt", "st"]]) {
  $(id).onchange = () => { state.ind[key] = $(id).checked; redraw(); };
}
for (const [id, key, lo, hi, whole] of [["iEma1Len", "ema1Len", 1, 500, true], ["iEma2Len", "ema2Len", 1, 500, true],
                                        ["iStF", "stF", 0.1, 50, false], ["iStAtr", "stAtr", 1, 500, true]]) {
  $(id).onchange = () => {
    let v = Number($(id).value);
    if (!Number.isFinite(v)) v = state.ind[key];
    v = Math.min(hi, Math.max(lo, whole ? Math.round(v) : v));
    $(id).value = v;
    state.ind[key] = v;
    refetch();
  };
}
$("basket").onchange = () => {
  const v = $("basket").value;
  if (v === "__adhoc") return;
  ADHOC = "";
  state.basket = v;
  history.replaceState(null, "", location.pathname + "?basket=" + encodeURIComponent(v));
  refetch();
};
document.addEventListener("click", (ev) => {
  const box = $("indBox");
  if (box.open && !box.contains(ev.target)) box.open = false;
});

async function loadBaskets() {
  let list = [];
  try { list = (await api("/api/baskets")).baskets || []; } catch (e) { setStatus(e.message, true); }
  const opts = [];
  if (ADHOC) opts.push(`<option value="__adhoc">Unsaved legs (from the option chain)</option>`);
  for (const b of list) {
    opts.push(`<option value="${esc(b.id)}">${esc(b.name)} · ${b.leg_count} legs</option>`);
  }
  if (!opts.length) opts.push('<option value="">no baskets saved yet</option>');
  $("basket").innerHTML = opts.join("");
  if (ADHOC) $("basket").value = "__adhoc";
  else if (list.some((b) => b.id === state.basket)) $("basket").value = state.basket;
  else if (list.length) { state.basket = list[0].id; $("basket").value = state.basket; save(); }
  else state.basket = "";
}

async function boot() {
  if (!LWC || !LWC.createChart) {
    setStatus("Lightweight Charts failed to load from /static", true);
    return;
  }
  const url = new URLSearchParams(location.search);
  if (url.get("legs")) ADHOC = url.get("legs");
  if (url.get("basket")) { state.basket = url.get("basket"); ADHOC = ""; }
  const tf = normTf(url.get("tf"));
  if (tf) state.tf = tf;
  save();
  makePane("spot", "Spot");
  makePane("combo", "Combo");
  makePane("call", "Call");
  makePane("put", "Put");
  applyControls();
  await loadBaskets();
  await refresh(true);
  startTimer();
}
boot();
</script>
</body>
</html>
"""
