"""One-page option chain: calls | strike | puts with OI, OI change and buildup.

Plain HTML and CSS, no framework, no build step. Every contract has a Chart button
and B / S buttons that add it to a basket built at the bottom of the page.
"""

CHAIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="/static/ui-theme.js"></script>
<title>Option Chain · Saidarshan</title>
<style>
  :root {
    --bg:#0f1216; --panel:#171c22; --panel2:#1c2229; --line:#2a323c; --text:#e6edf3;
    --muted:#9aa7b4; --up:#3fb950; --down:#f85149; --warn:#d29922; --accent:#58a6ff;
    --cebar:rgba(248,81,73,.22); --pebar:rgba(63,185,80,.22); --itm:#1d2530;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:13px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
  a { color:var(--accent); }
  header { position:sticky; top:0; z-index:20; background:#0f1216f2; backdrop-filter:blur(6px);
    border-bottom:1px solid var(--line); padding:9px 14px; display:flex; gap:12px;
    align-items:flex-end; flex-wrap:wrap; }
  h1 { font-size:14px; margin:0 8px 4px 0; font-weight:650; align-self:center; }
  h1 a { color:var(--muted); text-decoration:none; font-weight:500; margin-left:10px; font-size:13px; }
  h1 a:hover { color:var(--accent); }
  label.f { display:flex; flex-direction:column; gap:3px; font-size:11px; color:var(--muted); }
  select,input,button { background:#0d1117; color:var(--text); border:1px solid var(--line);
    border-radius:6px; padding:5px 8px; font:inherit; }
  /* A textbox with suggestions, not a dropdown: hide Chrome's datalist arrow. */
  input[list]::-webkit-calendar-picker-indicator { display:none !important; }
  input.und { width:150px; text-transform:uppercase; }
  input[type=number] { width:64px; }
  button { background:#21262d; cursor:pointer; }
  button:hover:not(:disabled) { background:#2d333b; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  button.go { background:#1f6f37; border-color:#2a8f47; }
  button.go:hover:not(:disabled) { background:#25833f; }
  button.danger { background:#6b2026; border-color:#8b2b32; }
  button.danger:hover:not(:disabled) { background:#7d262d; }
  button.sm { padding:1px 7px; font-size:11.5px; }
  /* Buy / sell ink follows the theme (ui-theme.css), so B and S read on light buttons too. */
  button.b { color:var(--buy-ink, #8ee29e); font-weight:650; }
  button.s { color:var(--sell-ink, #ffb3b3); font-weight:650; }
  :focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
  .grow { margin-left:auto; }
  .pill { font-size:11.5px; color:var(--muted); border:1px solid var(--line);
    border-radius:999px; padding:2px 9px; align-self:center; }
  .pill.bad { color:#ffb3b3; border-color:#7d232b; background:#4a1218; }

  main { padding:10px 14px 16px; }
  .meta { display:flex; gap:18px; flex-wrap:wrap; font-size:12.5px; margin:2px 0 10px;
    font-variant-numeric:tabular-nums; }
  .meta b { font-weight:650; }
  .warn { color:var(--warn); }
  .scroll { overflow-x:auto; border:1px solid var(--line); border-radius:9px; background:var(--panel); }
  table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
  th,td { padding:4px 7px; border-bottom:1px solid var(--line); white-space:nowrap; text-align:right; }
  thead th { position:sticky; top:0; background:var(--panel2); color:var(--muted); font-weight:600;
    font-size:11px; text-transform:uppercase; letter-spacing:.02em; }
  thead tr.sides th { font-size:12px; color:var(--text); text-align:center; }
  td.l, th.l { text-align:left; }
  td.strike { text-align:center; font-weight:650; background:#11161c; min-width:78px; }
  tr.atm td.strike { background:#1b2a44; color:#cfe3ff; }
  td.itm { background:var(--itm); }
  td.act { text-align:center; }
  td.act button { margin:0 1px; }
  td.ltp strong { font-weight:600; }
  td.ltp span { font-size:11px; margin-left:3px; }
  tr.spotrow td { text-align:center; font-size:11px; color:var(--accent); padding:1px;
    border-bottom:2px solid #264a7a; background:#0f1216; }
  tbody tr:hover td { filter:brightness(1.18); }
  .up { color:var(--up); } .down { color:var(--down); } .mut { color:var(--muted); }
  .tag { font-size:11px; padding:1px 6px; border-radius:4px; border:1px solid transparent; }
  .tag.lb { color:#8ee29e; background:#12301c; border-color:#24502e; }   /* long buildup */
  .tag.sb { color:#ffb3b3; background:#3a1418; border-color:#6b2026; }   /* short buildup */
  .tag.sc { color:#9fd8ff; background:#10283a; border-color:#1f4a6b; }   /* short covering */
  .tag.lu { color:#f2cc60; background:#33280b; border-color:#5c4408; }   /* long unwinding */
  .legend { display:flex; gap:10px; flex-wrap:wrap; margin:8px 0 0; font-size:11.5px; color:var(--muted); }
  [hidden] { display:none !important; }

  /* Basket builder, pinned to the bottom so it stays in reach while scrolling. */
  aside.basket { position:sticky; bottom:0; z-index:15; margin-top:14px; background:var(--panel);
    border:1px solid var(--accent); border-radius:9px; padding:9px 12px;
    box-shadow:0 -6px 22px var(--shadow, #0008); }
  aside.basket.empty { border-color:var(--line); box-shadow:none; }
  .bkhead { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .bkhead h2 { font-size:12.5px; margin:0; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
  .bkhead input.name { width:220px; }
  .bkhead label.f { flex-direction:row; align-items:center; gap:5px; font-size:12px; }
  #bkLegs td { padding:3px 7px; }
  #bkMsg { margin:6px 0 0; font-size:12.5px; }
  #bkMsg.bad { color:var(--sell-ink, #ffb3b3); } #bkMsg.ok { color:var(--buy-ink, #8ee29e); }

  @media (max-width:760px) {
    header { position:static; padding:7px 8px; gap:8px; align-items:center; }
    header h1 { width:100%; margin-bottom:0; }
    header label.f { flex:1 1 105px; min-width:0; }
    header input.und, header select { width:100%; max-width:100%; }
    header .grow { display:none; }
    #undHint { flex:1 1 100%; }
    main { padding:8px; max-width:100%; overflow:hidden; }
    .meta { gap:6px 12px; }
    aside.basket { position:static; max-height:none; margin-top:10px; padding:9px 8px; }
    .bkhead { align-items:stretch; }
    .bkhead > * { max-width:100%; }
    .bkhead input.name { width:100%; flex:1 1 100%; }
    .bkhead label.f { flex:1 1 130px; justify-content:space-between; }
    .bkhead .grow { display:none; }
    .bkhead button { flex:1 1 120px; }
  }
</style>
<link rel="stylesheet" href="/static/ui-theme.css" />
</head>
<body>
<header>
  <h1 id="pageTitle">Option chain</h1>
  <label class="f" for="und">Underlying
    <input id="und" class="und" list="undlist" autocomplete="off" spellcheck="false"
           placeholder="NIFTY" aria-describedby="undHint" />
  </label>
  <datalist id="undlist"></datalist>
  <label class="f" for="exp">Expiry <select id="exp"><option value="">nearest</option></select></label>
  <label class="f" for="strikes">Strikes each side
    <select id="strikes"><option>5</option><option selected>8</option><option>10</option>
      <option>15</option></select></label>
  <label class="f" for="win">Buildup window
    <select id="win"><option value="1">1 min</option><option value="3">3 min</option>
      <option value="5" selected>5 min</option><option value="15">15 min</option></select></label>
  <label class="f" for="refresh">Refresh
    <select id="refresh"><option value="0">off</option><option value="60000" selected>60s</option>
      <option value="120000">120s</option></select></label>
  <button type="button" id="load" class="go">Load chain</button>
  <span id="undHint" class="mut" style="font-size:11.5px;align-self:center">type an index or F&amp;O stock</span>
  <label class="theme-picker" for="themeSelect">Theme
    <select id="themeSelect" data-theme-select><option value="night">Night</option><option value="light">Light</option></select>
  </label>
  <div class="grow"></div>
  <span id="status" class="pill" role="status" aria-live="polite">…</span>
</header>

<main>
  <div class="meta" id="meta"></div>
  <div class="scroll">
    <table aria-describedby="meta">
      <thead>
        <tr class="sides"><th colspan="6">CALLS</th><th></th><th colspan="6">PUTS</th></tr>
        <tr>
          <th>Actions</th><th class="l" title="Price move against OI move over the buildup window">Buildup</th>
          <th title="OI change over the buildup window">OI chg (win)</th>
          <th title="OI change against the previous session">OI chg</th>
          <th>OI</th><th>LTP (chg %)</th>
          <th>Strike</th>
          <th>LTP (chg %)</th><th>OI</th>
          <th title="OI change against the previous session">OI chg</th>
          <th title="OI change over the buildup window">OI chg (win)</th>
          <th class="l" title="Price move against OI move over the buildup window">Buildup</th><th>Actions</th>
        </tr>
      </thead>
      <tbody id="chain"><tr><td colspan="13" class="mut" style="text-align:center">Loading…</td></tr></tbody>
    </table>
  </div>
  <div class="legend">
    <span><span class="tag lb">Long Buildup</span> price ↑ OI ↑</span>
    <span><span class="tag sb">Short Buildup</span> price ↓ OI ↑</span>
    <span><span class="tag sc">Short Covering</span> price ↑ OI ↓</span>
    <span><span class="tag lu">Long Unwinding</span> price ↓ OI ↓</span>
    <span>Shaded cells are in the money. OI bars are relative to the largest OI shown.
      Prices are the latest 1-minute candle unless an Upstox token gives live quotes.</span>
  </div>

  <aside class="basket empty" id="bk" aria-label="Basket builder">
    <div class="bkhead">
      <h2>Basket <span id="bkN"></span></h2>
      <input id="bkName" class="name" maxlength="60" placeholder="basket name (optional)"
             aria-label="Basket name" />
      <label class="f" for="bkSl">Stop % per leg
        <input id="bkSl" type="number" min="0.1" max="99" step="0.1" /></label>
      <label class="f" for="bkTp">Target % per leg
        <input id="bkTp" type="number" min="0.1" step="0.1" placeholder="none" /></label>
      <label class="f" for="bkOrd" title="Limit sends every leg at its own price; each fills when its price comes">Order
        <select id="bkOrd"><option value="MARKET">Market</option><option value="LIMIT">Limit</option></select></label>
      <label class="f" for="bkProd" title="Intraday is squared off at the square-off time; delivery (NRML) is carried">Product
        <select id="bkProd"><option value="INTRADAY">Intraday</option><option value="DELIVERY">Delivery (NRML)</option></select></label>
      <span id="bkNet" class="mut"></span>
      <div class="grow"></div>
      <button type="button" id="bkCombo"
        title="Spot, combined premium, calls and puts of these legs on one screen, without saving">Combo chart ↗</button>
      <button type="button" id="bkClear">Clear</button>
      <button type="button" id="bkSave" class="go">Save basket</button>
      <button type="button" id="bkExec" class="danger">Save &amp; execute</button>
    </div>
    <p id="bkEmpty" class="mut" style="margin:6px 0 0">Press <b>B</b> (buy) or <b>S</b> (sell)
      on any contract to add it here. Saved baskets are listed in Option Seller › Basket,
      and can be charted with indicators like any symbol.</p>
    <div class="scroll" id="bkTable" hidden style="margin-top:8px">
      <table>
        <thead><tr><th class="l">Leg</th><th class="l">Side</th><th>Lots</th><th>Qty</th>
          <th>LTP</th><th>Premium</th><th id="bkLimitHead" hidden>Limit price</th><th></th></tr></thead>
        <tbody id="bkLegs"></tbody>
      </table>
    </div>
    <p id="bkMsg" role="status" aria-live="polite"></p>
  </aside>
</main>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const KEY = sessionStorage.getItem("mthKey") || "";
/* Option Seller's chain (app shell) keeps its own preferences and basket builder; the
   original /chain keeps the original key. The first visit copies the original. */
const WS = (window.SAIDARSHAN_CONTEXT && window.SAIDARSHAN_CONTEXT.workspace) || null;
const WS_STORE = window.SaidarshanStore || { key: (k) => k, migrate: () => false };
const FIRST_VISIT = WS ? localStorage.getItem(WS_STORE.key("matheranChain.v1")) === null
                         && localStorage.getItem("matheranChain.v1") === null : false;
WS_STORE.migrate("matheranChain.v1");
const STORE = WS_STORE.key("matheranChain.v1");
const INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"];
const wsq = (path) => (WS ? path + (path.indexOf("?") >= 0 ? "&" : "?") + "workspace=" + encodeURIComponent(WS) : path);
/* Where the chain hands off to: the same workspace's views, or the original pages. */
const chartsUrl = () => (WS ? "/app/" + WS.replace(/_/g, "-") + "/chart" : "/charts");
const comboUrl = () => (WS ? "/app/" + WS.replace(/_/g, "-") + "/combo-chart" : "/combo");
const basketsUrl = () => (WS ? "/app/" + WS.replace(/_/g, "-") + "/basket" : "/app/option-seller/basket");
const winName = (what) => (WS ? "saidarshan-" + what + "-" + WS : "matheran" + what[0].toUpperCase() + what.slice(1));

let prefs = loadPrefs();
let DATA = null;          // last chain response
let timer = null;
let MODE = "paper";
let loading = false;
let lastSaved = null;     // basket returned by the last save

function loadPrefs() {
  const base = { und: "NIFTY", expiry: "", strikes: 8, window: 5, refresh: 60000,
                 legs: [], name: "", sl: "", tp: "" };
  try {
    const p = JSON.parse(localStorage.getItem(STORE) || "null");
    if (p && typeof p === "object") return { ...base, ...p, legs: Array.isArray(p.legs) ? p.legs : [] };
  } catch (e) { /* defaults */ }
  return base;
}
function savePrefs() { try { localStorage.setItem(STORE, JSON.stringify(prefs)); } catch (e) {} }

async function api(path, opts = {}) {
  const h = { "Accept": "application/json", "Content-Type": "application/json" };
  if (KEY) h["X-API-Key"] = KEY;
  const res = await fetch(path, { headers: h, ...opts });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = { detail: text }; }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : JSON.stringify(d || res.statusText));
  }
  return body;
}

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
const num = (v, d = 2) => (v == null || v === "" || Number.isNaN(Number(v))) ? "—" : Number(v).toFixed(d);
function compact(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v), a = Math.abs(n);
  if (a >= 1e7) return (n / 1e7).toFixed(2) + " Cr";
  if (a >= 1e5) return (n / 1e5).toFixed(2) + " L";
  return Math.round(n).toLocaleString("en-IN");
}
const signed = (v, f = compact) => (v == null ? "—" : (Number(v) > 0 ? "+" : "") + f(v));
const tone = (v) => (v > 0 ? "up" : v < 0 ? "down" : "mut");
const rupees = (v) => "₹" + Math.abs(Number(v)).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const BUILDUP = { "Long Buildup": "lb", "Short Buildup": "sb", "Short Covering": "sc", "Long Unwinding": "lu" };

function setStatus(text, bad) {
  $("status").textContent = text;
  $("status").className = "pill" + (bad ? " bad" : "");
}

/* The underlying's own chart id: an index spot, or the stock for stock options. */
function underlyingChartId(und) {
  return INDICES.includes(und) ? "idx:" + und : "eq:NSE:" + und;
}
function openCharts(symbols, tf) {
  const q = new URLSearchParams({ symbols: symbols.slice(0, 8).join(","), tf: tf || "5m" });
  window.open(chartsUrl() + "?" + q.toString(), winName("charts"));
}

/* -------------------------------------------------------------- the chain */
async function loadChain() {
  if (loading) return;
  const und = ($("und").value || prefs.und || "NIFTY").trim().toUpperCase();
  $("und").value = und;
  if (und !== prefs.und) { prefs.expiry = ""; $("exp").value = ""; }
  prefs.und = und;
  prefs.expiry = $("exp").value;
  prefs.strikes = Number($("strikes").value);
  prefs.window = Number($("win").value);
  savePrefs();

  const q = new URLSearchParams({ underlying: und, strikes: String(prefs.strikes),
                                  window: String(prefs.window) });
  if (prefs.expiry) q.set("expiry", prefs.expiry);
  loading = true;
  $("load").disabled = true;
  const started = Date.now();
  setStatus(DATA ? "refreshing…" : "loading chain… the first load fetches each contract's history");
  try {
    const d = await api("/api/options/oichain?" + q.toString());
    render(d);
    setStatus(`${d.rows.length} strikes · ${Date.now() - started} ms` +
      (d.errors ? ` · ${d.errors} contracts failed` : ""), d.errors > 0);
  } catch (e) {
    setStatus(e.message + (String(e.message).indexOf("X-API-Key") >= 0
      ? "  →  open Saidarshan (/app) first and enter the dashboard password" : ""), true);
    if (!DATA) $("chain").innerHTML = `<tr><td colspan="13" class="down" style="text-align:center">${esc(e.message)}</td></tr>`;
  } finally {
    loading = false;
    $("load").disabled = false;
  }
}

function fillExpiries(list, chosen) {
  const sel = $("exp");
  const want = prefs.expiry || "";
  sel.innerHTML = `<option value="">nearest${chosen && !want ? " (" + esc(chosen) + ")" : ""}</option>` +
    (list || []).slice(0, 16).map((e) => `<option value="${esc(e)}">${esc(e)}</option>`).join("");
  sel.value = want && (list || []).includes(want) ? want : "";
}

function render(d) {
  DATA = d;
  fillExpiries(d.expiries, d.expiry);
  const t = d.totals || {};
  $("meta").innerHTML = `
    <span><b>${esc(d.underlying)}</b> ${esc(d.expiry)}${d.expires_today ? ' <span class="warn">expires today</span>' : ""}</span>
    <span>Spot <b>${num(d.spot)}</b> <span class="mut">(${esc(d.reference_symbol)})</span></span>
    <span>ATM <b>${num(d.atm_strike, 0)}</b> · step ${num(d.strike_step, 0)}</span>
    <span title="Put OI divided by call OI across the strikes shown">PCR <b>${t.pcr == null ? "—" : num(t.pcr)}</b></span>
    <span>Call OI ${compact(t.ce_oi)} <span class="${tone(t.ce_oi_change)}">(${signed(t.ce_oi_change)})</span></span>
    <span>Put OI ${compact(t.pe_oi)} <span class="${tone(t.pe_oi_change)}">(${signed(t.pe_oi_change)})</span></span>
    <span class="mut">as of ${d.as_of ? new Date(d.as_of).toLocaleTimeString("en-IN", { hour12: false }) : "—"}
      · buildup over ${d.window_minutes} min</span>`;

  const rows = d.rows || [];
  if (!rows.length) {
    $("chain").innerHTML = '<tr><td colspan="13" class="mut" style="text-align:center">No strikes.</td></tr>';
    return;
  }
  let maxOi = 1;
  for (const r of rows) for (const q of [r.ce, r.pe]) if (q && q.oi > maxOi) maxOi = q.oi;

  let html = "";
  let spotShown = false;
  for (const r of rows) {
    if (!spotShown && r.strike > d.spot) {
      html += spotRow(d.spot);
      spotShown = true;
    }
    html += strikeRow(r, d, maxOi);
  }
  if (!spotShown) html += spotRow(d.spot);
  $("chain").innerHTML = html;

  $("chain").querySelectorAll("[data-chart]").forEach((b) => {
    b.onclick = () => openCharts([b.dataset.chart, underlyingChartId(d.underlying)], "5m");
  });
  $("chain").querySelectorAll("[data-add]").forEach((b) => {
    b.onclick = () => addLeg(b.dataset.key, b.dataset.add);
  });
  renderBasket();
}

function spotRow(spot) {
  return `<tr class="spotrow"><td colspan="13">spot ${num(spot)}</td></tr>`;
}

function sideCells(q, opt, itm, maxOi, win) {
  const x = itm ? " itm" : "";
  if (!q) {
    const empty = `<td class="mut${x}">—</td>`;
    return { act: `<td class="act${x}"></td>`, bu: empty, oiw: empty, oic: empty, oi: empty,
             ltp: empty };
  }
  const key = `${opt}:${q.strike}`;
  const pct = Math.max(0, Math.min(100, ((q.oi || 0) / maxOi) * 100)).toFixed(1);
  const bar = opt === "CE" ? "var(--cebar)" : "var(--pebar)";
  // Bars grow away from the strike column, so both sides read outward.
  const dir = opt === "CE" ? "to left" : "to right";
  const err = q.error ? ` title="${esc(q.error)}"` : "";
  return {
    act: `<td class="act${x}">
      <button type="button" class="sm" data-chart="${esc(q.chart_symbol)}"
        title="Chart ${esc(q.symbol)} beside its underlying">Chart</button>
      <button type="button" class="sm b" data-add="BUY" data-key="${esc(key)}"
        aria-label="Add BUY ${esc(q.symbol)} to the basket" title="Add BUY to the basket">B</button>
      <button type="button" class="sm s" data-add="SELL" data-key="${esc(key)}"
        aria-label="Add SELL ${esc(q.symbol)} to the basket" title="Add SELL to the basket">S</button></td>`,
    bu: `<td class="l${x}"${q.buildup_day ? ` title="On the day: ${esc(q.buildup_day)}"` : ""}>${q.buildup
      ? `<span class="tag ${BUILDUP[q.buildup] || ""}">${esc(q.buildup)}</span>` : '<span class="mut">—</span>'}</td>`,
    oiw: `<td class="${tone(q.oi_buildup)}${x}"
      title="OI ${signed(q.oi_buildup)} and price ${signed(q.price_change_window, (v) => num(v))} over the last ${win} min">${signed(q.oi_buildup)}</td>`,
    oic: `<td class="${tone(q.oi_change)}${x}"
      title="${q.prev_close_oi ? num(q.oi_change_pct) + "% vs previous session OI " + compact(q.prev_close_oi) : "no previous session OI"}">${signed(q.oi_change)}</td>`,
    oi: `<td class="${x.trim()}" style="background-image:linear-gradient(${dir}, ${bar} ${pct}%, transparent ${pct}%)">${compact(q.oi)}</td>`,
    ltp: `<td class="ltp${x}"${err}>${q.error ? '<span class="down">error</span>' : `<strong>${num(q.ltp)}</strong>
      <span class="${tone(q.change)}">${q.change_pct == null ? "" : signed(q.change_pct, (v) => num(v)) + "%"}</span>`}</td>`,
  };
}

function strikeRow(r, d, maxOi) {
  const ce = sideCells(r.ce, "CE", r.strike < d.spot, maxOi, d.window_minutes);
  const pe = sideCells(r.pe, "PE", r.strike > d.spot, maxOi, d.window_minutes);
  return `<tr class="${r.atm ? "atm" : ""}">
    ${ce.act}${ce.bu}${ce.oiw}${ce.oic}${ce.oi}${ce.ltp}
    <td class="strike">${num(r.strike, r.strike % 1 ? 2 : 0)}${r.atm ? ' <span style="font-size:10px">ATM</span>' : ""}</td>
    ${pe.ltp}${pe.oi}${pe.oic}${pe.oiw}${pe.bu}${pe.act}
  </tr>`;
}

function quoteByKey(key) {
  if (!DATA) return null;
  const [opt, strike] = key.split(":");
  const row = (DATA.rows || []).find((r) => String(r.strike) === strike);
  return row ? row[opt === "CE" ? "ce" : "pe"] : null;
}

/* ------------------------------------------------------------- the basket */
function addLeg(key, side) {
  const q = quoteByKey(key);
  if (!q) return;
  const existing = prefs.legs.find((l) => l.symbol === q.chart_symbol);
  if (existing) {
    // Same contract again: the server refuses a basket that buys and sells one
    // contract, so pressing the other side flips the leg instead of adding one.
    if (existing.side === side) existing.lots += 1;
    else existing.side = side;
  } else {
    if (prefs.legs.length >= 10) { bkMessage("A basket is limited to 10 legs.", true); return; }
    prefs.legs.push({ symbol: q.chart_symbol, label: q.symbol, side, lots: 1,
                      lot_size: q.lot_size || 1, ltp: q.ltp, underlying: DATA.underlying });
  }
  lastSaved = null;
  savePrefs();
  renderBasket();
  bkMessage(`${side} ${q.symbol} added.`, false);
}

/* Latest price for a leg: from the chain on screen when it is the same contract. */
function legPrice(leg) {
  if (DATA && leg.underlying === DATA.underlying) {
    for (const r of DATA.rows || []) {
      for (const q of [r.ce, r.pe]) if (q && q.chart_symbol === leg.symbol && q.ltp != null) return q.ltp;
    }
  }
  return leg.ltp;
}

function renderBasket() {
  const legs = prefs.legs;
  $("bk").classList.toggle("empty", !legs.length);
  $("bkEmpty").hidden = legs.length > 0;
  $("bkTable").hidden = legs.length === 0;
  $("bkN").textContent = legs.length ? `(${legs.length} leg${legs.length > 1 ? "s" : ""})` : "";
  $("bkSave").disabled = $("bkExec").disabled = $("bkClear").disabled = $("bkCombo").disabled = !legs.length;

  let net = 0, priced = true;
  const limit = $("bkOrd").value === "LIMIT";
  $("bkLimitHead").hidden = !limit;
  $("bkLegs").innerHTML = legs.map((l, i) => {
    const ltp = legPrice(l);
    const qty = l.lots * l.lot_size;
    const prem = ltp == null ? null : ltp * qty;
    if (prem == null) priced = false;
    else net += l.side === "SELL" ? prem : -prem;
    const lim = l.limit != null ? l.limit : (ltp != null ? Number(ltp).toFixed(2) : "");
    return `<tr>
      <td class="l">${esc(l.label)}</td>
      <td class="l"><select data-side="${i}" aria-label="Side for ${esc(l.label)}">
        <option value="BUY" ${l.side === "BUY" ? "selected" : ""}>BUY</option>
        <option value="SELL" ${l.side === "SELL" ? "selected" : ""}>SELL</option></select></td>
      <td><input type="number" min="1" step="1" value="${l.lots}" data-lots="${i}"
                 aria-label="Lots for ${esc(l.label)}" /></td>
      <td>${qty}</td><td>${num(ltp)}</td>
      <td class="${l.side === "SELL" ? "up" : "down"}">${prem == null ? "—" : (l.side === "SELL" ? "+" : "−") + rupees(prem)}</td>
      ${limit ? `<td><input type="number" min="0.05" step="0.05" value="${esc(lim)}" data-limit="${i}"
                 style="width:84px" aria-label="Limit price for ${esc(l.label)}" /></td>` : ""}
      <td><button type="button" class="sm" data-rm="${i}" aria-label="Remove ${esc(l.label)}">✕</button></td>
    </tr>`;
  }).join("");
  $("bkLegs").querySelectorAll("[data-limit]").forEach((el) => {
    el.onchange = () => {
      const v = Number(el.value);
      prefs.legs[Number(el.dataset.limit)].limit = v > 0 ? v : null;
      savePrefs();
    };
  });
  $("bkNet").innerHTML = !legs.length ? "" : !priced ? "net premium: —"
    : net >= 0 ? `net credit <b class="up">${rupees(net)}</b>` : `net debit <b class="down">${rupees(net)}</b>`;

  $("bkLegs").querySelectorAll("[data-side]").forEach((el) => {
    el.onchange = () => { prefs.legs[Number(el.dataset.side)].side = el.value; lastSaved = null; savePrefs(); renderBasket(); };
  });
  $("bkLegs").querySelectorAll("[data-lots]").forEach((el) => {
    el.onchange = () => {
      const v = Math.max(1, Math.floor(Number(el.value) || 1));
      prefs.legs[Number(el.dataset.lots)].lots = v; lastSaved = null; savePrefs(); renderBasket();
    };
  });
  $("bkLegs").querySelectorAll("[data-rm]").forEach((el) => {
    el.onclick = () => { prefs.legs.splice(Number(el.dataset.rm), 1); lastSaved = null; savePrefs(); renderBasket(); };
  });
}

function bkMessage(text, bad) {
  const el = $("bkMsg");
  el.textContent = text;
  el.className = bad ? "bad" : "ok";
}

function defaultName() {
  const und = [...new Set(prefs.legs.map((l) => l.underlying))].join("+");
  return `${und} ${prefs.legs.map((l) => (l.side === "SELL" ? "S " : "B ") + l.label.replace(und + " ", "")).join(", ")}`.slice(0, 60);
}

async function saveBasket() {
  if (!prefs.legs.length) return null;
  if (lastSaved) return lastSaved;
  const sl = $("bkSl").value.trim(), tp = $("bkTp").value.trim();
  const body = {
    name: $("bkName").value.trim() || defaultName(),
    legs: prefs.legs.map((l) => ({ symbol: l.symbol, direction: l.side === "SELL" ? "SHORT" : "LONG",
                                   lots: l.lots, label: l.label })),
    timeframe_minutes: 5,
    stop_loss_pct: sl ? Number(sl) : null,
    target_pct: tp ? Number(tp) : null,
    product: $("bkProd").value,
    // Baskets belong to Option Seller; the original /chain names none and gets the same.
    workspace: WS || "option_seller",
  };
  const basket = await api("/api/baskets", { method: "POST", body: JSON.stringify(body) });
  lastSaved = basket;
  return basket;
}

function savedLinks(basket, legs) {
  const el = $("bkMsg");
  el.insertAdjacentHTML("beforeend", ` &nbsp; <a href="#" id="bkChart">Chart basket with indicators ↗</a>
    &nbsp; <a href="${comboUrl()}?basket=${encodeURIComponent(basket.id)}" target="${winName("combo")}">Combo screen ↗</a>
    &nbsp; <a href="${basketsUrl()}">Manage in Basket</a>`);
  $("bkChart").onclick = (ev) => { ev.preventDefault(); openCharts([basket.chart_symbol, ...legs], "5m"); };
}

/* The unsaved legs on the combo screen: symbol@side@lots, as /api/combo reads them. */
$("bkCombo").onclick = () => {
  if (!prefs.legs.length) return;
  const legs = prefs.legs.map((l) => `${l.symbol}@${l.side}@${l.lots}`).join(",");
  window.open(comboUrl() + "?" + new URLSearchParams({ legs, tf: "5m" }).toString(), winName("combo"));
};

$("bkSave").onclick = async () => {
  try {
    const basket = await saveBasket();
    bkMessage(`Saved "${basket.name}" — ${basket.leg_count} legs.`, false);
    savedLinks(basket, prefs.legs.map((l) => l.symbol));
  } catch (e) { bkMessage(e.message, true); }
};

$("bkExec").onclick = async () => {
  const legs = prefs.legs;
  if (!legs.length) return;
  const ord = $("bkOrd").value, prod = $("bkProd").value;
  const limits = {};
  if (ord === "LIMIT") {
    for (const el of $("bkLegs").querySelectorAll("[data-limit]")) {
      const v = Number(el.value);
      const leg = legs[Number(el.dataset.limit)];
      if (!(v > 0)) { bkMessage(`Enter a limit price for ${leg.label}.`, true); el.focus(); return; }
      limits[leg.symbol] = v;
    }
  }
  const lines = legs.map((l) => `  ${l.side} ${l.lots * l.lot_size} × ${l.label}` +
    (ord === "LIMIT" ? ` @ ${num(limits[l.symbol])}` : "")).join("\n");
  const sl = $("bkSl").value.trim();
  if (!confirm((MODE === "live" ? "LIVE — REAL MONEY\n\n" : "Paper mode (simulated)\n\n") +
      `Execute this basket ${ord === "LIMIT" ? "as limit orders" : "at market"} now ` +
      `(${prod === "DELIVERY" ? "delivery / NRML" : "intraday"})?\n\n${lines}\n\nBought legs are sent first. ` +
      (ord === "LIMIT" ? "Each leg rests until its own price comes, so the legs can fill at different times. " : "") +
      `Each leg gets its own ${sl ? sl + "%" : "default"} protective stop.`)) return;
  $("bkExec").disabled = true;
  const legSymbols = legs.map((l) => l.symbol);
  let basket = null;
  try {
    basket = await saveBasket();
    const r = await api(`/api/baskets/${basket.id}/execute`, { method: "POST",
      body: JSON.stringify({ confirm: true, order_type: ord, product: prod,
                             limit_prices: ord === "LIMIT" ? limits : null,
                             workspace: WS || "option_seller" }) });
    const failed = (r.legs || []).filter((x) => x.status !== "sent");
    if (!failed.length) {
      bkMessage(`Executed "${basket.name}": ${r.sent} orders sent (${r.mode}).`, false);
      prefs.legs = []; lastSaved = null; savePrefs(); renderBasket();
    } else {
      bkMessage(`${r.partial ? "PARTIAL: " : ""}${r.sent} sent, ${failed.length} failed — ` +
        failed.map((x) => `${x.label || x.symbol}: ${x.error}`).join("; "), true);
    }
  } catch (e) { bkMessage(e.message, true); }
  // Saved even when execution was refused, so it can still be charted or retried.
  if (basket) savedLinks(basket, legSymbols);
  $("bkExec").disabled = !prefs.legs.length;
};

$("bkClear").onclick = () => {
  if (!confirm("Remove every leg from this basket?")) return;
  prefs.legs = []; lastSaved = null; savePrefs(); renderBasket(); bkMessage("", false);
};
["bkName", "bkSl", "bkTp"].forEach((id) => {
  $(id).onchange = () => {
    prefs.name = $("bkName").value; prefs.sl = $("bkSl").value; prefs.tp = $("bkTp").value;
    lastSaved = null; savePrefs();
  };
});
$("bkOrd").onchange = () => { prefs.ord = $("bkOrd").value; savePrefs(); renderBasket(); };
$("bkProd").onchange = () => { prefs.prod = $("bkProd").value; lastSaved = null; savePrefs(); };

/* ------------------------------------------------------------------ boot */
function startTimer() {
  if (timer) { clearInterval(timer); timer = null; }
  prefs.refresh = Number($("refresh").value);
  savePrefs();
  if (prefs.refresh > 0) {
    timer = setInterval(() => { if (!document.hidden) loadChain(); }, prefs.refresh);
  }
}

$("load").onclick = loadChain;
$("und").onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); loadChain(); } };
$("und").onchange = () => { if ($("und").value.trim().toUpperCase() !== prefs.und) loadChain(); };
$("exp").onchange = loadChain;
$("strikes").onchange = loadChain;
$("win").onchange = loadChain;
$("refresh").onchange = startTimer;

async function boot() {
  $("und").value = prefs.und;
  $("strikes").value = String(prefs.strikes);
  $("win").value = String(prefs.window);
  $("refresh").value = String(prefs.refresh);
  $("bkName").value = prefs.name || "";
  $("bkSl").value = prefs.sl || "";
  $("bkTp").value = prefs.tp || "";
  $("bkOrd").value = prefs.ord === "LIMIT" ? "LIMIT" : "MARKET";
  if (prefs.prod) $("bkProd").value = prefs.prod;
  renderBasket();
  try {
    const st = await api(wsq("/api/status"));
    MODE = st.mode;
    $("bkSl").placeholder = String((st.risk && st.risk.stop_loss_pct) || 3);
    if (!prefs.prod && st.risk && st.risk.default_product) $("bkProd").value = st.risk.default_product;
    // A workspace's first visit starts from its Setup defaults.
    const wd = st.workspace_defaults;
    if (FIRST_VISIT && wd) {
      if (wd.underlying) { prefs.und = wd.underlying; $("und").value = wd.underlying; }
      if (wd.chain_strikes) { prefs.strikes = wd.chain_strikes; $("strikes").value = String(wd.chain_strikes); }
      if (wd.chain_window) { prefs.window = wd.chain_window; $("win").value = String(wd.chain_window); }
      if (wd.product && !prefs.prod) $("bkProd").value = wd.product;
      if (wd.stop_loss_pct != null && !prefs.sl) { prefs.sl = String(wd.stop_loss_pct); $("bkSl").value = prefs.sl; }
      if (wd.target_pct != null && !prefs.tp) { prefs.tp = String(wd.target_pct); $("bkTp").value = prefs.tp; }
      savePrefs();
    }
  } catch (e) { /* the chain call below reports auth problems */ }
  try {
    const d = await api("/api/options/underlyings");
    $("undlist").innerHTML = (d.underlyings || []).map((u) => `<option value="${esc(u)}"></option>`).join("");
  } catch (e) { /* suggestions are optional */ }
  await loadChain();
  startTimer();
}
boot();
</script>
</body>
</html>
"""
