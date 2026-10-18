"""Single-file trading console. No build step, no external assets, no CDN."""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="/static/ui-theme.js"></script>
<title>Matheran trading console</title>
<style>
  :root {
    --bg:#0f1216; --panel:#171c22; --panel2:#1c2229; --line:#2a323c; --text:#e6edf3;
    --muted:#9aa7b4; --up:#3fb950; --down:#f85149; --warn:#d29922; --accent:#58a6ff;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
  a { color:var(--accent); }

  header { position:sticky; top:0; z-index:20; background:#0f1216ee;
    backdrop-filter:blur(6px); border-bottom:1px solid var(--line); padding:10px 16px; }
  .bar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  h1 { font-size:15px; margin:0; font-weight:650; letter-spacing:.01em; }
  .grow { margin-left:auto; }

  .pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
    border:1px solid var(--line); color:var(--muted); white-space:nowrap; }
  .pill.live { background:#4a1218; color:#ffb3b3; border-color:#7d232b; font-weight:650; }
  .pill.paper { background:#12301c; color:#8ee29e; border-color:#24502e; }
  .pill.on { background:#3a2c08; color:#f2cc60; border-color:#5c4408; }
  .pill.bad { background:#4a1218; color:#ffb3b3; border-color:#7d232b; }

  nav[role=tablist] { display:flex; gap:4px; margin-top:10px; flex-wrap:wrap; }
  nav button { background:transparent; border:1px solid transparent; border-bottom:2px solid transparent;
    color:var(--muted); padding:7px 14px; border-radius:6px 6px 0 0; cursor:pointer; font:inherit; }
  nav button:hover { color:var(--text); background:#1c2229; }
  nav button[aria-selected=true] { color:var(--text); border-bottom-color:var(--accent); font-weight:600; }
  nav button .dot { display:inline-block; width:7px; height:7px; border-radius:50%;
    background:var(--warn); margin-left:6px; vertical-align:middle; }

  main { padding:16px; max-width:1560px; }
  section.panel { background:var(--panel); border:1px solid var(--line); border-radius:9px;
    padding:14px 16px; margin-bottom:16px; }
  h2 { font-size:13px; margin:0 0 4px; font-weight:650; text-transform:uppercase;
    letter-spacing:.05em; color:var(--muted); }
  .sub { color:var(--muted); font-size:12.5px; margin:0 0 12px; }

  table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
  th,td { text-align:right; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }
  th.l,td.l { text-align:left; }
  th { color:var(--muted); font-weight:600; font-size:11.5px; text-transform:uppercase; }
  tbody tr:hover { background:var(--panel2); }
  tr.ready td { background:#12301c; }
  .scroll { overflow-x:auto; }

  button { background:#21262d; color:var(--text); border:1px solid var(--line);
    border-radius:6px; padding:6px 13px; cursor:pointer; font:inherit; }
  button:hover:not(:disabled) { background:#2d333b; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  button.go { background:#1f6f37; border-color:#2a8f47; }
  button.go:hover:not(:disabled) { background:#25833f; }
  button.danger { background:#6b2026; border-color:#8b2b32; }
  button.danger:hover:not(:disabled) { background:#7d262d; }
  button.sm { padding:3px 9px; font-size:12.5px; }
  :focus-visible { outline:2px solid var(--accent); outline-offset:1px; }

  input,select { background:#0d1117; color:var(--text); border:1px solid var(--line);
    border-radius:6px; padding:6px 9px; font:inherit; }
  input[type=number] { width:96px; }
  input[type=checkbox] { width:16px; height:16px; accent-color:var(--accent); }
  label.f { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--muted); }
  label.inline { flex-direction:row; align-items:center; gap:7px; color:var(--text); font-size:13px; }
  form.row, .row { display:flex; gap:11px; align-items:flex-end; flex-wrap:wrap; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px; }

  .cred { border:1px solid var(--line); border-radius:8px; padding:12px 14px;
    margin-bottom:12px; background:var(--panel2); }
  .cred header { position:static; background:none; border:none; padding:0;
    display:flex; align-items:center; gap:10px; margin-bottom:4px; backdrop-filter:none; }
  .cred h3 { margin:0; font-size:13.5px; }
  .cred .note { color:var(--muted); font-size:12px; margin:4px 0 10px; }
  .credrow { display:grid; grid-template-columns:minmax(150px,1fr) minmax(190px,1.4fr) auto;
    gap:10px; align-items:center; padding:7px 0; border-top:1px solid var(--line); }
  .credrow .nm { font-size:13px; }
  .credrow .hint { color:var(--muted); font-size:11.5px; display:block; margin-top:1px; }
  code { background:#0d1117; padding:1px 5px; border-radius:4px; font-size:12px; }

  .card { border:1px solid var(--warn); border-radius:8px; padding:12px 14px;
    margin-bottom:10px; background:#241f0d; }
  .card h3 { margin:0 0 7px; font-size:14px; }
  .kv { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr));
    gap:3px 14px; font-size:12.5px; margin:7px 0; }
  .chk { font-size:12.5px; }
  .up,.yes { color:var(--up); } .down,.no2 { color:var(--down); }
  .mut { color:var(--muted); } .yes { font-weight:650; }
  .warnbox { border:1px solid var(--warn); background:#241f0d; border-radius:8px;
    padding:10px 13px; margin-bottom:14px; display:flex; gap:12px; align-items:center;
    flex-wrap:wrap; font-size:13px; }
  .errbox { border:1px solid #7d232b; background:#2b1417; border-radius:8px;
    padding:10px 13px; margin-bottom:14px; font-size:13px; color:#ffb3b3; }
  .okbox { border:1px solid #24502e; background:#12301c; border-radius:8px;
    padding:10px 13px; margin-bottom:14px; font-size:13px; color:#8ee29e; }
  [hidden] { display:none !important; }
  .sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }

  /* Baskets */
  .bkcard { border:1px solid var(--line); border-radius:8px; padding:10px 12px;
    margin-bottom:12px; background:var(--panel2); }
  .bkcard.open { border-color:#2a8f47; }
  .bkcard.partial { border-color:#8b2b32; }
  .bkcard .top { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:7px; }
  .bkcard h3 { margin:0; font-size:14px; }
  .bkcard .nums { font-size:12.5px; font-variant-numeric:tabular-nums; }
  input.bksym { width:280px; }
  /* A textbox with suggestions, not a dropdown: hide Chrome's datalist arrow. */
  input[list]::-webkit-calendar-picker-indicator { display:none !important; }
  .tagb { font-size:11px; padding:1px 6px; border-radius:4px; border:1px solid var(--line);
    color:var(--muted); margin-left:4px; }

  /* Exit rule builder: one row per condition, parameters as text boxes. */
  table.rules td { vertical-align:middle; }
  .opnd { display:flex; gap:6px; align-items:center; flex-wrap:nowrap; }
  .opnd .pp { display:flex; align-items:center; gap:4px; font-size:11.5px; color:var(--muted); }
  .opnd input.rp { width:66px; padding:4px 6px; }
  .opnd input.rp.bad { border-color:var(--down); }
  .rulebox { margin-top:10px; border:1px solid var(--line); border-radius:8px; padding:9px 12px;
    font-size:13px; background:var(--panel2); display:grid; gap:4px; }
  .rulebox.bad { border-color:#7d232b; color:#ffb3b3; background:#2b1417; }
  .rulebox:empty { display:none; }

  /* Order dialog: market or limit, the product, and what closes the trade. */
  dialog.ord { background:var(--panel); color:var(--text); border:1px solid var(--line);
    border-radius:10px; padding:0; width:min(560px, calc(100vw - 20px)); box-shadow:0 18px 60px #000b; }
  dialog.ord::backdrop { background:#000a; }
  .ordbody { padding:14px 16px 12px; display:grid; gap:11px; }
  .ordbody h2 { margin:0; font-size:15px; text-transform:none; letter-spacing:0; color:var(--text); }
  .ordbody .mode { font-size:12px; border-radius:6px; padding:4px 9px; }
  .ordbody .mode.paper { background:#12301c; color:#8ee29e; border:1px solid #24502e; }
  .ordbody .mode.live { background:#4a1218; color:#ffb3b3; border:1px solid #7d232b; font-weight:650; }
  .ordbody fieldset { border:none; margin:0; padding:0; min-width:0; }
  .seg { display:inline-flex; border:1px solid var(--line); border-radius:7px; overflow:hidden; }
  .seg input { position:absolute; opacity:0; width:1px; height:1px; }
  .seg label { padding:6px 14px; cursor:pointer; font-size:13px; }
  .seg label + input + label { border-left:1px solid var(--line); }
  .seg input:checked + label { background:#2d333b; font-weight:650; }
  .seg input:focus-visible + label { outline:2px solid var(--accent); outline-offset:-2px; }
  .ordbody .hint { color:var(--muted); font-size:12.5px; margin:0; display:grid; gap:2px; }
  .ordbody .err { color:#ffb3b3; font-size:12.5px; margin:0; }
  .ordbody .err:empty { display:none; }
  .ordbody .actions { display:flex; justify-content:flex-end; gap:8px; }
  .ordbody td, .ordbody th { padding:4px 6px; }
  .ordbody input.lim { width:104px; }
  td.rdy { font-weight:650; color:var(--up); }

  /* Scanner */
  #p-scanner h3 { font-size:13px; margin:14px 0 6px; font-weight:650; }
  #p-scanner fieldset { border:1px solid var(--line); border-radius:8px; padding:8px 12px 10px; margin:0 0 12px; }
  #p-scanner legend { color:var(--muted); font-size:12px; padding:0 4px; }
  .scunis { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:6px 14px; }
  .scunis .err { color:#ffb3b3; font-size:12px; display:block; }
  ul.chips { list-style:none; display:flex; flex-wrap:wrap; gap:6px; padding:0; margin:8px 0 0; }
  ul.chips li { border:1px solid var(--line); border-radius:999px; padding:2px 4px 2px 10px;
    font-size:12.5px; display:flex; align-items:center; gap:6px; background:var(--panel2); }
  ul.chips:empty { display:none; }
  #scProg { width:min(420px, 100%); height:12px; vertical-align:middle; }
  .scprog { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:10px; font-size:13px; }
  th button.sortb { background:none; border:none; padding:0; color:inherit; font:inherit;
    text-transform:inherit; cursor:pointer; }
  th button.sortb:hover { color:var(--text); }
  table.scres td.l, table.scres th.l { text-align:left; }
  table.scres caption { text-align:left; font-weight:650; padding:4px 0 6px; }
  table.scres { margin-bottom:14px; }
  table.scres tbody th { color:var(--text); text-transform:none; font-size:inherit; font-weight:600; }
  #scNotes { margin:6px 0 0; padding-left:18px; }
  #scNotes:empty { display:none; }

  @media (max-width:760px) {
    header { padding:6px 8px; }
    header > .bar { flex-wrap:nowrap; overflow-x:auto; align-items:center; gap:8px;
      scrollbar-width:thin; -webkit-overflow-scrolling:touch; }
    header > .bar > * { flex:none; }
    header > .bar > .grow { margin-left:0; }
    header > .bar .row { flex-wrap:nowrap; width:auto; }
    header > .bar label[for="key"] { min-width:190px !important; }
    nav[role=tablist] { flex-wrap:nowrap; overflow-x:auto; margin-top:5px;
      scrollbar-width:thin; -webkit-overflow-scrolling:touch; }
    nav[role=tablist] > * { flex:none; }
    nav[role=tablist] button, nav[role=tablist] a { min-height:44px; padding:10px 12px !important; }
    main { width:100%; max-width:100%; min-width:0; padding:8px; }
    section.panel { padding:11px 10px; margin-bottom:10px; }
    form.row, .row { max-width:100%; min-width:0; }
    label.f { min-width:0; max-width:100%; }
    input, select { max-width:100%; min-width:0; }
    input.bksym { width:min(280px, 72vw); }
    .grid { grid-template-columns:minmax(0,1fr); }
    .credrow { grid-template-columns:minmax(0,1fr); align-items:stretch; }
    .scunis { grid-template-columns:minmax(0,1fr); }
    .opnd { min-width:max-content; }
    dialog.ord { max-height:calc(100dvh - 16px); overflow:auto; }
    .ordbody { padding:12px 10px; }
    .ordbody .actions { position:sticky; bottom:0; background:var(--panel); padding-top:6px; }
  }
</style>
<link rel="stylesheet" href="/static/ui-theme.css" />
</head>
<body>
<header>
  <div class="bar">
    <h1>Matheran</h1>
    <span id="pMode" class="pill">…</span>
    <span id="pBroker" class="pill">…</span>
    <span id="pMarket" class="pill">…</span>
    <span id="pAuth" class="pill">…</span>
    <span id="pHalt" class="pill on" hidden>HALTED</span>
    <label class="theme-picker" for="themeSelect">Theme
      <select id="themeSelect" data-theme-select><option value="night">Night</option><option value="light">Light</option></select>
    </label>
    <div class="grow row" style="align-items:center">
      <label class="f" for="key" style="min-width:230px"
             title="This app's own password (MATHERAN_API_KEY in .env). Not a Dhan or Upstox credential.">
        Password for this dashboard
        <input id="key" type="password" autocomplete="off"
               placeholder="MATHERAN_API_KEY from .env" />
      </label>
      <button id="btnKey" type="button" title="Store the key for this browser tab">Use</button>
      <button id="btnHalt" type="button" class="danger">Halt</button>
      <button id="btnResume" type="button" hidden>Resume</button>
    </div>
  </div>
  <nav role="tablist" aria-label="Sections">
    <button role="tab" id="tab-setup"    aria-controls="p-setup"    aria-selected="false">Setup</button>
    <button role="tab" id="tab-trade"    aria-controls="p-trade"    aria-selected="true">Trade</button>
    <button role="tab" id="tab-options"  aria-controls="p-options"  aria-selected="false">Options</button>
    <button role="tab" id="tab-scanner"  aria-controls="p-scanner"  aria-selected="false">Scanner</button>
    <button role="tab" id="tab-baskets"  aria-controls="p-baskets"  aria-selected="false">Baskets</button>
    <button role="tab" id="tab-strategy" aria-controls="p-strategy" aria-selected="false">Strategy</button>
    <button role="tab" id="tab-journal"  aria-controls="p-journal"  aria-selected="false">Journal</button>
    <a href="/charts" style="margin-left:8px;align-self:center;color:var(--accent);
       text-decoration:none;font-size:13px;padding:7px 12px">Charts ↗</a>
    <a href="/chain" style="align-self:center;color:var(--accent);
       text-decoration:none;font-size:13px;padding:7px 12px">Option chain ↗</a>
  </nav>
</header>

<main>
  <div id="msg" role="status" aria-live="polite"></div>
  <div id="dirty" class="warnbox" hidden>
    <strong>Credentials or mode changed.</strong>
    <span>Apply them to load the new broker into the running engine.</span>
    <button type="button" id="btnApply" class="go">Apply now</button>
  </div>
  <div id="dataErr" class="errbox" hidden>
    <strong>No market data.</strong>
    <span id="dataErrMsg"></span>
    <p style="margin:8px 0 0">Nothing can be computed without candles — Advanced VWAP, RSI,
      Supertrend and ADX all need them, so no signal will ever fire. Either subscribe to
      Dhan Data APIs (₹499 + taxes per month, under DhanHQ Trading APIs on web.dhan.co),
      or switch the broker to <strong>Paper only (synthetic data)</strong> on the Setup tab
      to keep working meanwhile.</p>
  </div>

  <!-- ============================== SETUP ============================== -->
  <div role="tabpanel" id="p-setup" aria-labelledby="tab-setup" hidden>
    <section class="panel">
      <h2>Connection</h2>
      <p class="sub">Which broker the engine uses, and whether orders are real.
        Secrets are written to <code id="envPath">.env</code> with owner-only permissions
        and are never sent back to this page.</p>
      <form class="row" id="connForm">
        <label class="f" for="cfgMode">Mode
          <select id="cfgMode">
            <option value="paper">paper — orders simulated</option>
            <option value="live">live — REAL orders</option>
          </select>
        </label>
        <label class="f" for="cfgBroker">Orders go to
          <select id="cfgBroker">
            <option value="dhan">Dhan (DhanHQ v2)</option>
            <option value="stoxkart">Stoxkart (Superr)</option>
            <option value="paper">Nobody — simulated only</option>
          </select>
        </label>
        <label class="f" for="cfgData">Market data from
          <select id="cfgData">
            <option value="upstox">Upstox — free, no credentials</option>
            <option value="dhan">Dhan — needs the ₹499/mo Data API plan</option>
            <option value="">Same as order broker</option>
            <option value="synthetic">Synthetic — generated prices</option>
          </select>
        </label>
        <button type="submit" class="go">Save connection</button>
        <button type="button" id="btnTest">Test connection</button>
        <button type="button" id="btnApply2" class="go">Apply to engine</button>
      </form>
      <div id="testOut" style="margin-top:12px"></div>
    </section>

    <section class="panel">
      <h2>Credentials</h2>
      <p class="sub">Leave a box empty to keep the stored value. Press Clear to remove one.</p>
      <div id="creds"><p class="mut">Loading…</p></div>
      <div class="row" style="margin-top:6px">
        <button type="button" id="btnSaveCreds" class="go">Save credentials</button>
        <button type="button" id="btnGenKey">Generate console API key</button>
      </div>
    </section>
  </div>

  <!-- ============================== TRADE ============================== -->
  <div role="tabpanel" id="p-trade" aria-labelledby="tab-trade">
    <section class="panel">
      <h2>Approvals waiting <span id="apprN" class="mut"></span></h2>
      <p class="sub">No position is ever opened without you pressing Approve here.</p>
      <div id="appr" aria-live="polite"><p class="mut">Nothing waiting.</p></div>
    </section>

    <section class="panel">
      <h2>Add a stock to watch</h2>
      <form class="row" id="addForm">
        <label class="f" for="sym">Symbol<input id="sym" required placeholder="RELIANCE" size="13" /></label>
        <label class="f" for="exch">Exchange
          <select id="exch"><option>NSE</option><option>BSE</option></select></label>
        <label class="f" for="dir">Direction
          <select id="dir">
            <option value="LONG">LONG — buy, then sell</option>
            <option value="SHORT">SHORT — sell, then buy back</option>
            <option value="BOTH">BOTH — buy above Advanced VWAP, sell below</option>
          </select>
        </label>
        <label class="f" for="qty">Quantity<input id="qty" type="number" min="1" step="1" value="1" required /></label>
        <label class="f" for="tf">Timeframe
          <select id="tf" data-tf="5"></select></label>
        <label class="f" for="tradeCandle">Candle type
          <select id="tradeCandle"><option value="normal">Normal candle</option>
            <option value="heikin_ashi">Heikin Ashi</option></select></label>
        <label class="f" for="sl">Stop %<input id="sl" type="number" min="0.1" max="50" step="0.1" value="3" /></label>
        <label class="f" for="tp">Target %<input id="tp" type="number" min="0.1" step="0.1" placeholder="none" /></label>
        <label class="f" for="prod" title="Intraday is squared off at the square-off time; delivery (CNC) is carried until its exits fire">Product
          <select id="prod"><option value="">default</option><option value="INTRADAY">Intraday</option>
            <option value="DELIVERY">Delivery (CNC)</option></select></label>
        <label class="f" for="exm" title="What closes its trades">Exit by
          <select id="exm"><option value="">Strategy tab default</option>
            <option value="both">SL / target + exit conditions</option>
            <option value="sl_target">SL / target only</option>
            <option value="strategy">Exit conditions only (no stop)</option></select></label>
        <button type="submit" class="go">Watch</button>
      </form>
    </section>

    <section class="panel">
      <h2>Watches</h2>
      <div class="scroll">
        <table>
          <thead><tr>
            <th class="l">Instrument</th><th class="l">Dir</th><th class="l">Kind</th><th>TF</th><th>Candle</th><th>Qty</th>
            <th class="l">State</th><th>LTP</th><th>Advanced VWAP</th><th>RSI</th><th>EMA(RSI,21)</th>
            <th>Supertrend</th><th>ADX</th>
            <th title="Every entry condition satisfied on the last closed candle; hover for each condition">Ready</th>
            <th>Entry</th><th>Stop</th><th>P&amp;L</th>
            <th class="l">Note</th><th></th>
          </tr></thead>
          <tbody id="watches"><tr><td colspan="19" class="mut">No watches yet.</td></tr></tbody>
        </table>
      </div>
    </section>
  </div>

  <!-- ============================= OPTIONS ============================= -->
  <div role="tabpanel" id="p-options" aria-labelledby="tab-options" hidden>
    <div role="tablist" aria-label="Option views" class="row"
         style="align-items:center;margin:0 0 10px;gap:6px">
      <button type="button" role="tab" id="opt-tab-scan" class="go"
              aria-controls="opt-panel-scan" aria-selected="true">Option scan</button>
      <button type="button" role="tab" id="opt-tab-straddle"
              aria-controls="opt-panel-straddle" aria-selected="false" tabindex="-1">Straddle</button>
    </div>

    <div role="tabpanel" id="opt-panel-scan" aria-labelledby="opt-tab-scan">
      <section class="panel">
        <h2>ATM and OTM scan</h2>
        <p class="sub">Current price, Advanced VWAP, RSI(21), EMA(RSI,21), EMA(21), Supertrend(21, 0.618)
          and ADX for the ATM strike plus OTM strikes on both sides. Rows highlighted green
          meet every entry condition. For open interest, OI change and the 5-minute buildup on
          every strike, open the <a href="/chain">full option chain ↗</a>.</p>
        <form class="row" id="chainForm">
          <label class="f" for="und">Underlying
            <select id="und"><option>NIFTY</option><option>BANKNIFTY</option><option>FINNIFTY</option>
              <option>MIDCPNIFTY</option><option>SENSEX</option></select></label>
          <label class="f" for="exp">Expiry<select id="exp"><option value="">nearest</option></select></label>
          <label class="f" for="otm">OTM count<input id="otm" type="number" min="0" max="20" value="5" /></label>
          <label class="f" for="otf">Timeframe
            <select id="otf" data-tf="1"></select></label>
          <label class="f" for="optCandle">Candle type
            <select id="optCandle"><option value="normal">Normal candle</option>
              <option value="heikin_ashi">Heikin Ashi</option></select></label>
          <label class="f" for="ref">ATM from
            <select id="ref"><option value="index">index spot</option><option value="future">future</option></select></label>
          <label class="f" for="amin">ADX min<input id="amin" type="number" min="0" step="1" value="20" /></label>
          <label class="f" for="lots">Lots to buy<input id="lots" type="number" min="1" step="1" value="1" /></label>
          <button type="submit" class="go" id="btnScan">Scan</button>
          <label class="inline" for="autoScan"><input type="checkbox" id="autoScan" /> Auto-refresh</label>
        </form>
        <p id="chainMeta" class="sub" style="margin:11px 0 0"></p>
        <div class="scroll" style="margin-top:6px">
          <table>
            <thead><tr>
              <th class="l">Contract</th><th class="l">Type</th><th>Strike</th>
              <th>LTP</th><th>Advanced VWAP</th><th>&gt;Advanced VWAP</th><th>RSI(21)</th><th>EMA(RSI,21)</th>
              <th>EMA(21)</th><th>Supertrend</th><th>ADX</th><th>Ready</th>
              <th class="l">Blocking condition</th><th>Actions</th>
            </tr></thead>
            <tbody id="chain"><tr><td colspan="14" class="mut">Press Scan.</td></tr></tbody>
          </table>
        </div>
      </section>
    </div>

    <div role="tabpanel" id="opt-panel-straddle" aria-labelledby="opt-tab-straddle" hidden>
      <section class="panel">
        <h2>Straddle monitor</h2>
        <p class="sub">CE + PE premium for ATM and seven listed strikes on either side (15 rows).
          Change is from the previous session's combined close. Above / below compares the displayed
          straddle price with Advanced VWAP and EMA(21) from the latest closed combined candle; trend uses
          Supertrend(21, 0.618). Direct broker quotes are used when available; paper mode may use clearly
          labelled reference prices for simulated execution only.</p>
        <form class="row" id="straddleForm">
          <label class="f" for="strUnd">Underlying
            <select id="strUnd"><option>NIFTY</option><option>BANKNIFTY</option><option>FINNIFTY</option>
              <option>MIDCPNIFTY</option><option>SENSEX</option></select></label>
          <label class="f" for="strExp">Expiry
            <select id="strExp"><option value="">nearest</option></select></label>
          <label class="f" for="strTf">Timeframe
            <select id="strTf" data-tf="1"></select></label>
          <label class="f" for="strCandle">Candle type
            <select id="strCandle"><option value="normal">Normal candle</option>
              <option value="heikin_ashi">Heikin Ashi</option></select></label>
          <label class="f" for="strLots">Lots per leg
            <input id="strLots" type="number" min="1" step="1" value="1" inputmode="numeric" /></label>
          <button type="submit" class="go" id="btnStraddle">Scan straddles</button>
        </form>
        <p id="straddleMeta" class="sub" style="margin:11px 0 0"></p>
        <div class="scroll" style="margin-top:6px">
          <table>
            <thead><tr>
              <th class="l">Strike</th><th>Straddle price</th><th>Change</th><th>Change %</th>
              <th>Close</th><th>Open</th><th>High</th><th>Low</th>
              <th>Advanced VWAP</th><th>Supertrend</th><th>EMA(21)</th><th>Status</th><th>Actions</th>
            </tr></thead>
            <tbody id="straddleRows"><tr><td colspan="13" class="mut">Press Scan straddles.</td></tr></tbody>
          </table>
        </div>
      </section>
    </div>
  </div>

  <!-- ============================= SCANNER ============================= -->
  <!-- Scanner controls carry their own ids and data-sc-* attributes only: never
       data-sec / data-key, which the Strategy tab's Save collects page-wide. -->
  <div role="tabpanel" id="p-scanner" aria-labelledby="tab-scanner" hidden>
    <section class="panel" aria-labelledby="scCondHead">
      <h2 id="scCondHead">Conditions</h2>
      <p class="sub">A live BUY / SELL screener. Scanning itself is read-only and never places an
        order or creates a watch. An explicit <strong>Add to watchlist</strong> action creates a normal
        one-share watch; it still waits for the configured watch conditions and your approval before
        any order. Each row is one condition on its own timeframe, written like
        the exit rules on the Strategy tab. <strong>live</strong> reads the forming candle at the
        live price (as TradingView draws it); <strong>last closed candle</strong> waits for the
        close. Rows are joined by AND / OR, AND binding tighter. A row without enough history is
        n/a and counts as not met.</p>
      <h3 id="scBuyHead">BUY when</h3>
      <div class="scroll">
        <table class="rules">
          <caption class="sr">BUY conditions</caption>
          <thead><tr>
            <th class="l" scope="col">Join</th><th class="l" scope="col">Timeframe</th>
            <th class="l" scope="col">Candle type</th><th class="l" scope="col">Indicator</th>
            <th class="l" scope="col">Condition</th>
            <th class="l" scope="col">Compared with</th><th class="l" scope="col">Checked</th>
            <th scope="col"><span class="sr">Move or remove</span></th>
          </tr></thead>
          <tbody id="scBuyRows"><tr><td colspan="8" class="l mut">Loading…</td></tr></tbody>
        </table>
      </div>
      <div class="row" style="margin-top:10px;align-items:center">
        <button type="button" id="scBuyAdd">+ Add condition</button>
        <button type="button" id="scReset" title="Back to the seven default BUY conditions">Reset to defaults</button>
      </div>
      <h3 id="scSellHead">SELL when</h3>
      <label class="inline" for="scLinked"><input type="checkbox" id="scLinked" checked />
        SELL mirrors BUY (above ↔ below, RSI levels reflected around 50)</label>
      <div class="scroll" style="margin-top:8px">
        <table class="rules">
          <caption class="sr">SELL conditions</caption>
          <thead><tr>
            <th class="l" scope="col">Join</th><th class="l" scope="col">Timeframe</th>
            <th class="l" scope="col">Candle type</th><th class="l" scope="col">Indicator</th>
            <th class="l" scope="col">Condition</th>
            <th class="l" scope="col">Compared with</th><th class="l" scope="col">Checked</th>
            <th scope="col"><span class="sr">Move or remove</span></th>
          </tr></thead>
          <tbody id="scSellRows"><tr><td colspan="8" class="l mut">Loading…</td></tr></tbody>
        </table>
      </div>
      <div class="row" style="margin-top:10px;align-items:center">
        <button type="button" id="scSellAdd" hidden>+ Add SELL condition</button>
      </div>
      <div id="scRuleText" class="rulebox" aria-live="polite"></div>
      <div class="row" style="margin-top:12px;align-items:center">
        <button type="button" id="scSave" class="go">Save scanner settings</button>
        <span id="scSaveState" class="mut" style="font-size:12.5px" role="status"></span>
      </div>
    </section>

    <section class="panel" aria-labelledby="scWhatHead">
      <h2 id="scWhatHead">What to scan</h2>
      <fieldset>
        <legend>Universes</legend>
        <div id="scUnis" class="scunis"><span class="mut">Loading…</span></div>
      </fieldset>
      <div class="row" style="align-items:flex-end">
        <label class="f" for="scSym">Custom symbol
          <input id="scSym" list="scSymList" autocomplete="off" spellcheck="false" size="24"
                 aria-label="Add a custom symbol" aria-describedby="scSymHint"
                 placeholder="RELIANCE, BSE:TCS, MCX:GOLD" /></label>
        <button type="button" id="scSymAdd">Add</button>
        <span id="scSymHint" class="mut" style="font-size:12.5px;align-self:center">e.g. RELIANCE, BSE:TCS, MCX:GOLD</span>
      </div>
      <datalist id="scSymList"></datalist>
      <ul id="scChips" class="chips" aria-label="Custom symbols"></ul>
      <p class="sub" style="margin:10px 0 0"><span id="scTotal" aria-live="polite"></span></p>
    </section>

    <section class="panel" aria-labelledby="scRunHead">
      <h2 id="scRunHead">Run</h2>
      <div class="row">
        <label class="f" for="scSide">Side
          <select id="scSide">
            <option value="both">Both</option><option value="buy">BUY only</option>
            <option value="sell">SELL only</option>
          </select></label>
        <label class="f" for="scEval">Evaluation
          <select id="scEval">
            <option value="auto">Auto</option><option value="complete">Every condition</option>
            <option value="lazy">Stop at the first failed condition</option>
          </select></label>
        <label class="f" for="scAuto">Auto-rescan
          <select id="scAuto" aria-describedby="scAutoHint">
            <option value="0">Off</option><option value="2">every 2 min</option>
            <option value="5">every 5 min</option><option value="10">every 10 min</option>
            <option value="15">every 15 min</option><option value="30">every 30 min</option>
            <option value="60">every 60 min</option>
          </select></label>
        <button type="button" id="scRun" class="go">Run scan</button>
        <button type="button" id="scCancel" class="danger" disabled>Cancel</button>
      </div>
      <p id="scAutoHint" class="mut" style="font-size:12.5px;margin:6px 0 0" hidden></p>
      <p id="scEst" class="sub" style="margin:10px 0 0" aria-live="polite"></p>
      <div class="scprog">
        <progress id="scProg" max="1" value="0" aria-label="Scan progress"></progress>
        <span id="scProgText" class="mut">No scan yet.</span>
      </div>
      <span id="scSr" class="sr" role="status" aria-live="polite"></span>
      <p id="scBudget" class="sub" style="margin:8px 0 0"></p>
    </section>

    <section class="panel" aria-labelledby="scResHead">
      <h2 id="scResHead">Results</h2>
      <div class="row" style="margin-bottom:10px">
        <label class="f" for="scFilter">Show
          <select id="scFilter">
            <option value="match">Matches only</option>
            <option value="atleast">At least N conditions met</option>
            <option value="all">Everything scanned</option>
          </select></label>
        <label class="f" for="scMinMet" id="scMinWrap" hidden>N conditions
          <input id="scMinMet" type="number" min="0" max="12" step="1" value="5" /></label>
      </div>
      <div id="scTables"><p class="mut">Run a scan to see results.</p></div>
      <p id="scFooter" class="sub" style="margin:4px 0 0"></p>
      <ul id="scNotes" class="sub"></ul>
    </section>
  </div>

  <!-- ============================= BASKETS ============================= -->
  <div role="tabpanel" id="p-baskets" aria-labelledby="tab-baskets" hidden>
    <section class="panel">
      <h2>New basket</h2>
      <p class="sub">A basket groups buy and sell legs for a spread, straddle or pair trade.
        Broker legs are submitted sequentially, not atomically. Each leg becomes a watch with its
        own stop, so every protection still applies. You can also build one from the
        <a href="/chain">option chain ↗</a> with its B / S buttons.</p>
      <div class="row">
        <label class="f" for="bkName">Name
          <input id="bkName" maxlength="60" placeholder="e.g. bull call spread" /></label>
        <label class="f" for="bkTf">Chart timeframe
          <select id="bkTf" data-tf="5"></select></label>
        <label class="f" for="bkProd" title="For every leg: intraday is squared off at the square-off time; delivery (CNC / NRML) is carried">Product
          <select id="bkProd"><option value="">default</option><option value="INTRADAY">Intraday</option>
            <option value="DELIVERY">Delivery (CNC / NRML)</option></select></label>
        <label class="f" for="bkExit" title="What closes each leg">Exit by
          <select id="bkExit"><option value="">Strategy tab default</option>
            <option value="both">SL / target + exit conditions</option>
            <option value="sl_target">SL / target only</option>
            <option value="strategy">Exit conditions only (no stop)</option></select></label>
        <label class="f" for="bkSl">Stop % per leg
          <input id="bkSl" type="number" min="0.1" max="99" step="0.1" placeholder="default" /></label>
        <label class="f" for="bkTp">Target % per leg
          <input id="bkTp" type="number" min="0.1" step="0.1" placeholder="none" /></label>
      </div>
      <div class="scroll" style="margin-top:10px">
        <table>
          <thead><tr><th class="l">Symbol</th><th class="l">Side</th>
            <th>Lots <span class="mut">(shares for stocks)</span></th>
            <th class="l">Resolves to</th><th></th></tr></thead>
          <tbody id="bkLegRows"></tbody>
        </table>
      </div>
      <datalist id="bkSymList"></datalist>
      <div class="row" style="margin-top:10px">
        <button type="button" id="bkAddLeg">+ Add leg</button>
        <button type="button" id="bkCreate" class="go">Save basket</button>
      </div>
    </section>

    <section class="panel">
      <h2>Baskets <span id="bkCount" class="mut"></span></h2>
      <p class="sub"><strong>Execute</strong> sends every leg now, at market or as limit orders at
        prices you set per leg, intraday or delivery, bought legs first. Premium is the sum or
        difference of the leg prices in points, as the basket chart draws it.
        <strong>Exit all</strong> buys back sold legs first, then sells the bought ones.
        <strong>Watch legs</strong> lets each leg wait for its own entry signal instead.
        <strong>Combo</strong> opens the underlying, the combined premium with Advanced VWAP, EMAs and
        Supertrend, and the call and put legs on one 2 × 2 screen.
        <strong>Chart</strong> opens the combined basket value with indicators, beside its legs.</p>
      <div id="bkList" aria-live="polite"><p class="mut">No baskets yet.</p></div>
    </section>
  </div>

  <!-- ============================ STRATEGY ============================ -->
  <div role="tabpanel" id="p-strategy" aria-labelledby="tab-strategy" hidden>
    <section class="panel">
      <h2>Entry rules</h2>
      <p class="sub">All of these must hold on the last closed candle: price above Advanced VWAP,
        RSI above its 21-EMA, price above Supertrend, and ADX above the minimum for options.
        A SHORT (sell) watch uses the mirror image: price below Advanced VWAP, RSI below its 21-EMA and
        price below Supertrend; a BOTH watch takes whichever side lines up.
        Saved to <code>config.yaml</code> and applied to the next evaluation immediately.</p>
      <div class="grid" id="entryGrid"></div>
    </section>

    <section class="panel" aria-labelledby="exitHead">
      <h2 id="exitHead">Exit rules</h2>
      <p class="sub">A position is closed by whichever comes first: the conditions below, the
        stop, the target or the square-off time. Each row is one condition: an indicator and
        its parameters, a comparison, then another indicator or a number. Join rows with AND /
        OR; AND binds tighter than OR, as in Pine Script. A row checked
        <strong>on candle close</strong> only reads candles that closed after the position was
        opened; a <strong>live price</strong> row reads the forming candle at the current price.</p>
      <div class="scroll">
        <table class="rules">
          <caption class="sr">Exit conditions</caption>
          <thead><tr>
            <th class="l" scope="col">Join</th><th class="l" scope="col">Candle type</th>
            <th class="l" scope="col">Indicator</th>
            <th class="l" scope="col">Condition</th><th class="l" scope="col">Compared with</th>
            <th class="l" scope="col">Checked</th><th scope="col"><span class="sr">Remove</span></th>
          </tr></thead>
          <tbody id="ruleRows"><tr><td colspan="7" class="l mut">Loading…</td></tr></tbody>
        </table>
      </div>
      <div class="row" style="margin-top:10px;align-items:center">
        <button type="button" id="ruleAdd">+ Add condition</button>
        <button type="button" id="ruleDefault"
                title="Back to RSI below its exit EMA, or close below Supertrend">Reset to the default two</button>
        <span id="ruleState" class="mut" style="font-size:12.5px" role="status"></span>
      </div>
      <div id="ruleText" class="rulebox" aria-live="polite"></div>

      <h2 style="margin-top:18px">Stop, target and session</h2>
      <p class="sub">Checked on the live price between candles.</p>
      <div class="grid" id="exitGrid"></div>
      <p class="sub" style="margin:12px 0 0" id="exitSummary"></p>
    </section>

    <section class="panel">
      <h2>Indicator periods</h2>
      <p class="sub">These feed the entry conditions and the charts, so the two cannot
        disagree. Exit conditions carry their own parameters, in the rows above.</p>
      <div class="grid" id="indGrid"></div>
    </section>

    <section class="panel">
      <h2>Engine, caps and session</h2>
      <div class="grid" id="engGrid"></div>
      <div class="row" style="margin-top:14px">
        <button type="button" id="btnSaveStrat" class="go">Save settings</button>
        <button type="button" id="btnReloadStrat">Discard changes</button>
      </div>
    </section>
  </div>

  <!-- ============================= JOURNAL ============================= -->
  <div role="tabpanel" id="p-journal" aria-labelledby="tab-journal" hidden>
    <section class="panel">
      <h2>Trades <span id="pnlSum" class="mut"></span></h2>
      <div class="scroll">
        <table>
          <thead><tr>
            <th class="l">Exit time</th><th class="l">Instrument</th><th class="l">Dir</th><th>Qty</th><th>Entry</th>
            <th>Exit</th><th>P&amp;L</th><th>%</th><th class="l">Reason</th><th class="l">Mode</th>
          </tr></thead>
          <tbody id="trades"><tr><td colspan="10" class="mut">No trades yet.</td></tr></tbody>
        </table>
      </div>
    </section>
    <section class="panel">
      <h2>Open positions</h2>
      <div class="scroll">
        <table>
          <thead><tr>
            <th class="l">Instrument</th><th class="l">Dir</th><th>Qty</th><th>Entry</th><th>LTP</th><th>Stop</th>
            <th>Target</th><th>Unrealised</th><th></th>
          </tr></thead>
          <tbody id="positions"><tr><td colspan="9" class="mut">Flat.</td></tr></tbody>
        </table>
      </div>
    </section>
  </div>
</main>

<dialog id="ord" class="ord" aria-labelledby="ordTitle">
  <form id="ordForm" class="ordbody" novalidate>
    <h2 id="ordTitle">Order</h2>
    <p class="sub" id="ordSub" style="margin:-6px 0 0"></p>
    <div id="ordMode" class="mode paper">PAPER · orders are simulated</div>
    <div class="row" style="align-items:flex-end">
      <fieldset class="seg"><legend class="sr">Order type</legend>
        <input type="radio" name="ordType" id="ordMkt" value="MARKET" checked /><label for="ordMkt">Market</label>
        <input type="radio" name="ordType" id="ordLmt" value="LIMIT" /><label for="ordLmt">Limit</label>
      </fieldset>
      <label class="f" for="ordLimit" id="ordLimitWrap">Limit price
        <input id="ordLimit" type="number" min="0" step="0.05" inputmode="decimal" /></label>
    </div>
    <div class="scroll" id="ordLegsWrap" hidden>
      <table>
        <caption class="sr">Basket legs</caption>
        <thead><tr><th class="l" scope="col">Leg</th><th class="l" scope="col">Side</th>
          <th scope="col">Qty</th><th scope="col">LTP</th><th scope="col" id="ordLegLimitHead">Limit price</th></tr></thead>
        <tbody id="ordLegs"></tbody>
      </table>
    </div>
    <div class="row">
      <label class="f" for="ordProduct">Product
        <select id="ordProduct">
          <option value="INTRADAY">Intraday — squared off at the square-off time</option>
          <option value="DELIVERY">Delivery — carried (CNC / NRML)</option>
        </select></label>
      <label class="f" for="ordExit">Exit by
        <select id="ordExit">
          <option value="both">SL / target + exit conditions</option>
          <option value="sl_target">SL / target only</option>
          <option value="strategy">Exit conditions only (no stop)</option>
        </select></label>
    </div>
    <div class="hint" id="ordHint" aria-live="polite"></div>
    <p class="err" id="ordErr" role="alert"></p>
    <div class="actions">
      <button type="button" id="ordCancel">Cancel</button>
      <button type="submit" id="ordOk" class="go">Place order</button>
    </div>
  </form>
</dialog>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
let KEY = sessionStorage.getItem("mthKey") || "";
let TAB = "trade";
let SETTINGS = null;
let SCAN_TIMER = null;
let STRADDLE_DATA = null;
let STATUS_NOTE = false;   // the message box currently shows a status-poll message
$("key").value = KEY;

/* ------------------------------------------------------------------ helpers */
async function api(path, opts = {}) {
  const h = { "Content-Type": "application/json" };
  if (KEY) h["X-API-Key"] = KEY;
  const res = await fetch(path, { headers: h, ...opts });
  const text = await res.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch (e) { body = { detail: text }; }
  if (!res.ok) {
    const d = body && body.detail;
    const err = new Error(typeof d === "string" ? d : JSON.stringify(d || res.statusText));
    err.status = res.status;   // network failures reject before this, without a status
    throw err;
  }
  return body;
}
let NOTE_SEQ = 0;
function note(text, kind) {
  const box = $("msg");
  const mine = ++NOTE_SEQ;
  if (!text) { box.innerHTML = ""; return; }
  box.innerHTML = '<div class="' + (kind === "ok" ? "okbox" : "errbox") + '"></div>';
  box.firstChild.textContent = text;
  // Only this message is cleared: a newer one keeps its own five seconds.
  if (kind === "ok") setTimeout(() => { if (mine === NOTE_SEQ && box.firstChild) box.innerHTML = ""; }, 5000);
}
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));

/* Tracks paper vs live so every Buy confirmation says which one you are in. */
let SETTINGS_MODE = "paper";

/* Translate an engine instrument into a chart symbol id. */
function chartSymbolFor(inst) {
  if (inst.instrument_type === "INDEX" || inst.segment === "IDX_I") {
    return "idx:" + inst.symbol;
  }
  if (inst.option_type && inst.underlying) {
    return `opt:${inst.underlying}:${inst.expiry}:${inst.strike}:${inst.option_type}`;
  }
  if ((inst.instrument_type || "").startsWith("FUT") && inst.underlying) {
    return `fut:${inst.underlying}:${inst.expiry}`;
  }
  const exch = (inst.segment || "").startsWith("BSE") ? "BSE" : "NSE";
  return `eq:${exch}:${inst.symbol}`;
}

/* Open the chart grid preloaded with these instruments. */
function openCharts(symbols, timeframe) {
  const q = new URLSearchParams({ symbols: symbols.filter(Boolean).join(",") });
  if (timeframe) q.set("tf", timeframe);
  window.open("/charts?" + q.toString(), "matheranCharts");
}
const n = (v, d = 2) =>
  (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) ? "—" : Number(v).toFixed(d);
const clock = (iso) => iso ? new Date(iso).toLocaleTimeString("en-IN", { hour12:false }) : "—";

/* Timeframes, the same table as the server's (timeframes.py). */
const TFS = [
  { id: "1m", minutes: 1, label: "1 min" }, { id: "3m", minutes: 3, label: "3 min" },
  { id: "5m", minutes: 5, label: "5 min" }, { id: "9m", minutes: 9, label: "9 min" },
  { id: "15m", minutes: 15, label: "15 min" }, { id: "30m", minutes: 30, label: "30 min" },
  { id: "1h", minutes: 60, label: "1 hour" }, { id: "2h", minutes: 120, label: "2 hours" },
  { id: "1D", minutes: 1440, label: "1 day" }, { id: "1W", minutes: 10080, label: "1 week" },
  { id: "1M", minutes: 43200, label: "1 month" },
];
const tfCode = (minutes) => (TFS.find((t) => t.minutes === Number(minutes)) || { id: minutes + "m" }).id;
function fillTfSelects() {
  document.querySelectorAll("select[data-tf]").forEach((sel) => {
    const want = String(sel.value || sel.dataset.tf);
    sel.innerHTML = TFS.map((t) => `<option value="${t.minutes}">${t.label}</option>`).join("");
    sel.value = TFS.some((t) => String(t.minutes) === want) ? want : sel.dataset.tf;
  });
}
const EXIT_TEXT = { both: "SL / target + exit conditions", sl_target: "SL / target only",
                    strategy: "exit conditions only" };
const isCash = (inst) => !!inst && /^(NSE|BSE)_EQ$/.test(inst.segment || "");
let RISK = {};            // /api/status risk block: defaults for the order dialog
let HAS_RULES = true;     // whether the Strategy tab has any exit conditions

/* --------------------------------------------------------------------- tabs */
const TABS = ["setup", "trade", "options", "scanner", "baskets", "strategy", "journal"];
function showTab(name) {
  TAB = name;
  TABS.forEach((t) => {
    const btn = $("tab-" + t), panel = $("p-" + t);
    const on = t === name;
    btn.setAttribute("aria-selected", on ? "true" : "false");
    btn.tabIndex = on ? 0 : -1;
    panel.hidden = !on;
  });
  location.hash = name;
  if (name === "setup" || name === "strategy") loadSettings();
  if (name === "journal") loadJournal();
  if (name === "options") loadExpiries();
  if (name === "scanner") loadScanner();
  if (name === "trade") loadTrade();
  if (name === "baskets") { ensureLegRows(); loadBaskets(); }
}

/* Side wording. Exit reasons are stored with long-side names; a short left on the
   mirror-image condition, so the text is flipped for it. */
const sideOf = (dir) => (dir === "SHORT" ? "SELL" : "BUY");
function reasonText(reason, dir) {
  let r = String(reason || "").replace(/_/g, " ");
  if (dir === "SHORT") {
    r = r.replace("rsi below exit signal", "rsi above exit signal")
         .replace("price below supertrend", "price above supertrend");
  }
  return r;
}
/* Options carry only their underlying as a "name", so show the trading symbol. */
function instName(inst) {
  if (!inst) return "";
  return inst.option_type ? (inst.symbol || inst.display_name) : (inst.display_name || inst.symbol);
}
function dirCell(dir) {
  return `<td class="l ${dir === "SHORT" ? "down" : "up"}">${esc(dir || "LONG")}</td>`;
}
TABS.forEach((t, i) => {
  const btn = $("tab-" + t);
  btn.onclick = () => showTab(t);
  btn.onkeydown = (ev) => {
    if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
    ev.preventDefault();
    const next = TABS[(i + (ev.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    showTab(next); $("tab-" + next).focus();
  };
});

/* ------------------------------------------------------------- header / key */
$("btnKey").onclick = () => {
  KEY = $("key").value.trim();
  sessionStorage.setItem("mthKey", KEY);
  note("Key stored for this browser tab.", "ok");
  refresh();
};
$("btnHalt").onclick = async () => {
  if (!confirm("Halt the engine? No new signals or entries will be raised.")) return;
  const sq = confirm("Also exit every open position at market right now?\n\nOK = exit all, Cancel = keep positions.");
  try { await api("/api/control/halt", { method:"POST", body: JSON.stringify({ square_off: sq, reason: "halted from console" }) });
    note(sq ? "Halted and squared off." : "Halted.", "ok"); } catch (e) { note(e.message); }
  refresh();
};
$("btnResume").onclick = async () => {
  try { await api("/api/control/resume", { method:"POST" }); note("Engine resumed.", "ok"); }
  catch (e) { note(e.message); }
  refresh();
};
$("btnApply").onclick = applyBroker;
$("btnApply2").onclick = applyBroker;
async function applyBroker() {
  try {
    const r = await api("/api/settings/broker/apply", { method:"POST" });
    note("Broker applied: " + r.broker + " (" + r.mode + ", data: " + r.data_source + ").", "ok");
  } catch (e) { note(e.message); }
  refresh(); loadSettings();
}

/* ------------------------------------------------------------------ setup */
async function loadSettings() {
  let s;
  const localHost = ["127.0.0.1", "localhost", "::1"].includes(location.hostname);
  const settingsPath = localHost ? "/api/settings" : "/api/settings-view";
  try { s = await api(settingsPath); } catch (e) { note(e.message); return; }
  SETTINGS = s;
  $("envPath").textContent = s.credentials.env_file;
  $("cfgMode").value = s.config.mode;
  $("cfgBroker").value = s.config.broker.name;
  $("cfgData").value = s.config.broker.data_broker || "";
  renderCreds(s.credentials);
  renderStrategyForm(s.config);
  loadRules(s.exit_rules);
}

function renderCreds(c) {
  $("creds").innerHTML = c.groups.map((g) => `
    <div class="cred">
      <header>
        <h3>${esc(g.label)}</h3>
        <span class="pill ${g.ready ? "paper" : ""}">${g.ready ? "ready" : "incomplete"}</span>
      </header>
      ${g.note ? `<p class="note">${esc(g.note)}</p>` : ""}
      ${g.fields.map((f) => `
        <div class="credrow">
          <div class="nm">
            <label for="cred-${esc(f.key)}">${esc(f.label)}</label>
            <span class="hint">${esc(f.help)}</span>
          </div>
          <input id="cred-${esc(f.key)}" data-cred="${esc(f.key)}"
                 type="${f.sensitive ? "password" : "text"}" autocomplete="off"
                 placeholder="${f.is_set ? esc(f.preview) : "not set"}" />
          <button type="button" class="sm danger clearCred" data-clear="${esc(f.key)}"
                  ${f.is_set ? "" : "disabled"}>Clear</button>
        </div>`).join("")}
    </div>`).join("");

  document.querySelectorAll(".clearCred").forEach((b) => {
    b.onclick = async () => {
      const k = b.dataset.clear;
      if (!confirm("Remove " + k + " from .env?")) return;
      try {
        await api("/api/settings/credentials", { method:"PUT", body: JSON.stringify({ values: { [k]: null } }) });
        note(k + " cleared.", "ok"); loadSettings(); refresh();
      } catch (e) { note(e.message); }
    };
  });
}

$("btnSaveCreds").onclick = async () => {
  const values = {};
  document.querySelectorAll("[data-cred]").forEach((el) => {
    const v = el.value.trim();
    if (v) values[el.dataset.cred] = v;
  });
  if (!Object.keys(values).length) { note("Nothing typed in — fill a field first."); return; }
  try {
    const r = await api("/api/settings/credentials", { method:"PUT", body: JSON.stringify({ values }) });
    note("Saved: " + r.saved.join(", ") + ". Press Apply to load them into the engine.", "ok");
    if (values.MATHERAN_API_KEY) {
      KEY = values.MATHERAN_API_KEY;
      sessionStorage.setItem("mthKey", KEY);
      $("key").value = KEY;
    }
    document.querySelectorAll("[data-cred]").forEach((el) => { el.value = ""; });
    loadSettings(); refresh();
  } catch (e) { note(e.message); }
};

$("btnGenKey").onclick = async () => {
  if (!confirm("Generate a new console API key? The old one stops working immediately.")) return;
  try {
    const r = await api("/api/settings/api-key/generate", { method:"POST" });
    KEY = r.api_key;
    sessionStorage.setItem("mthKey", KEY);
    $("key").value = KEY;
    note("New key generated and saved to .env: " + r.api_key + "  (copy it now, it is not shown again)", "ok");
    loadSettings(); refresh();
  } catch (e) { note(e.message); }
};

$("connForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const mode = $("cfgMode").value;
  if (mode === "live" && !confirm(
      "LIVE MODE\n\nOrders will be sent to your real broker account with real money.\n\nContinue?")) return;
  try {
    await api("/api/settings/config", { method:"PUT", body: JSON.stringify({
      mode,
      broker: { name: $("cfgBroker").value, data_broker: $("cfgData").value || null },
      confirm_live: mode === "live" }) });
    note("Connection saved. Press Apply to engine to switch the running broker.", "ok");
    loadSettings(); refresh();
  } catch (e) { note(e.message); }
};

$("btnTest").onclick = async () => {
  $("testOut").innerHTML = '<p class="mut">Testing…</p>';
  try {
    const r = await api("/api/settings/broker/test", { method:"POST" });
    if (!r.ok) { $("testOut").innerHTML = '<div class="errbox"></div>';
      $("testOut").firstChild.textContent = "Failed: " + (r.error || "unknown"); return; }
    const lines = Object.entries(r.health || {}).map(([k, v]) =>
      `<span>${esc(k)}: <strong>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</strong></span>`).join("");
    $("testOut").innerHTML = `<div class="okbox">
      Connected to <strong>${esc(r.broker)}</strong> · data source <strong>${esc(r.data_source)}</strong>
      · live orders ${r.live_orders_supported ? "supported" : "<strong>not supported</strong>"}
      <div class="kv" style="margin-top:6px">${lines}</div></div>`;
  } catch (e) { note(e.message); $("testOut").innerHTML = ""; }
};

/* --------------------------------------------------------------- strategy */
const ENTRY_FIELDS = [
  ["strategy","timeframe_minutes","Timeframe","select",TFS.map((t) => [t.minutes, t.label])],
  ["strategy","entry_candle_type","Candle type","select",[
    ["normal", "Normal candle"], ["heikin_ashi", "Heikin Ashi"]]],
  ["strategy","entry_condition_mode","Entry trigger","select",["state","cross"]],
  ["strategy","adx_min","ADX minimum (options)","num",null,0.5],
  ["strategy","require_adx","Require ADX for equities too","bool"],
  ["risk","allow_manual_buy","Allow the manual Buy / Sell and basket Execute buttons (skip the signal)","bool"],
];
// The indicator exits are the rule rows above; these are the price and clock exits.
const EXIT_FIELDS = [
  ["risk","stop_loss_pct","Stop loss % of capital deployed","num",null,0.1],
  ["risk","target_pct","Target % (blank = none)","num",null,0.1],
  ["risk","breakeven_trigger_pct","Move stop to entry after % profit (blank = off)","num",null,0.1],
  ["risk","place_stop_at_broker","Rest the stop order at the broker","bool"],
  ["risk","exit_mode","Close positions on","select",[
    ["both", "SL / target + exit conditions"], ["sl_target", "SL / target only"],
    ["strategy", "Exit conditions only (no stop)"]]],
  ["engine","default_product","Default product","select",[
    ["INTRADAY", "Intraday (squared off)"], ["DELIVERY", "Delivery (carried: CNC / NRML)"]]],
  ["risk","trail_profit_trigger_pct","Trailing profit: start after % profit (blank = off)","num",null,0.1],
  ["risk","trail_profit_value","Trailing profit: trail by","num",null,0.05],
  ["risk","trail_profit_unit","Trailing profit: trail by unit","select",[
    ["pct", "% of the best price"], ["pts", "points"]]],
  ["engine","square_off_time","Square off intraday positions at","text"],
  ["engine","no_new_entry_after","No new intraday entries after","text"],
];
const IND_FIELDS = [
  ["strategy","rsi_period","RSI period","num"],
  ["strategy","rsi_signal_entry_period","Entry signal EMA(RSI)","num"],
  ["strategy","rsi_signal_exit_period","Exit signal EMA(RSI)","num"],
  ["strategy","supertrend_period","Supertrend ATR period","num"],
  ["strategy","supertrend_factor","Supertrend factor","num",null,0.001],
  ["strategy","price_ema_period","Price EMA period","num"],
  ["strategy","adx_period","ADX period","num"],
];
const ENG_FIELDS = [
  ["engine","poll_seconds","Poll interval (s)","num"],
  ["engine","approval_ttl_seconds","Approval expires after (s)","num"],
  ["engine","cooldown_seconds","Cooldown after exit (s)","num"],
  ["engine","max_trades_per_day","Max trades per day per watch","num"],
  ["engine","max_open_positions","Max concurrent positions","num"],
  ["engine","market_open","Market open (HH:MM)","text"],
  ["engine","market_close","Market close (HH:MM)","text"],
];
function field(spec, cfg) {
  const [section, key, label, kind, choices, step] = spec;
  const value = (cfg[section] || {})[key];
  const id = "cfg-" + section + "-" + key;
  if (kind === "bool") {
    return `<label class="inline" for="${id}"><input type="checkbox" id="${id}"
      data-sec="${section}" data-key="${key}" ${value ? "checked" : ""} /> ${esc(label)}</label>`;
  }
  if (kind === "select") {
    // A select's value is always text; numeric choices are marked so Save sends
    // numbers back, which is what the config validation compares against. A choice is
    // a value, or [value, label].
    const opts = choices.map((c) => (Array.isArray(c) ? c : [c, c]));
    const numeric = opts.every(([v]) => typeof v === "number");
    return `<label class="f" for="${id}">${esc(label)}<select id="${id}" data-sec="${section}" data-key="${key}"
      ${numeric ? 'data-num="1"' : ""}>
      ${opts.map(([v, text]) => `<option value="${esc(v)}" ${String(v) === String(value) ? "selected" : ""}>${esc(text)}</option>`).join("")}
    </select></label>`;
  }
  const t = kind === "num" ? "number" : "text";
  const st = step ? ` step="${step}"` : (kind === "num" ? ' step="1"' : "");
  const v = value === null || value === undefined ? "" : value;
  return `<label class="f" for="${id}">${esc(label)}<input type="${t}"${st} id="${id}"
    data-sec="${section}" data-key="${key}" value="${esc(v)}" /></label>`;
}
function renderStrategyForm(cfg) {
  $("entryGrid").innerHTML = ENTRY_FIELDS.map((f) => field(f, cfg)).join("");
  $("exitGrid").innerHTML = EXIT_FIELDS.map((f) => field(f, cfg)).join("");
  $("indGrid").innerHTML = IND_FIELDS.map((f) => field(f, cfg)).join("");
  $("engGrid").innerHTML = ENG_FIELDS.map((f) => field(f, cfg)).join("");

  // Spell out in words what will actually close a position, so the settings above
  // cannot be misread.
  const r = cfg.risk;
  const mode = r.exit_mode || "both";
  const parts = [];
  if (mode !== "sl_target") parts.push("the exit conditions above");
  if (mode !== "strategy") {
    parts.push(`a ${r.stop_loss_pct}% stop on capital deployed`);
    if (r.target_pct) parts.push(`a ${r.target_pct}% target`);
    if (r.breakeven_trigger_pct) parts.push(`stop lifted to entry once ${r.breakeven_trigger_pct}% in profit`);
    if (r.trail_profit_trigger_pct && r.trail_profit_value) {
      parts.push(`a trailing profit: once ${r.trail_profit_trigger_pct}% in profit, the stop follows ` +
        `the best price ${r.trail_profit_value}${r.trail_profit_unit === "pts" ? " points" : "%"} behind`);
    }
  }
  parts.push(`for intraday positions, square-off at ${cfg.engine.square_off_time}`);
  $("exitSummary").textContent = "By default a position is closed by whichever comes first: " +
    parts.join("; ") + "." + (mode === "strategy"
      ? " Exit conditions only means no stop loss at all, so a trade can run against you until a condition fires."
      : " A short's stop sits above its entry.") +
    " A watch, an order or a basket can pick its own product and exit mode; orders placed from " +
    "the charts page also carry their own stop, trailing stop and target. Delivery positions " +
    "are carried overnight and never squared off.";
}

/* ------------------------------------------------------- exit rule builder */
let RULE_CAT = null;      // indicators and comparisons, from the server
let RULES = [];           // the rows on screen, edited in place
let RULES_DIRTY = false;  // edited since the last load or save
let RULES_RESET = false;  // "reset to the default two" pressed, not yet saved
let RULE_TIMER = null;

const clone = (x) => JSON.parse(JSON.stringify(x));
function operandSpec(id) { return (RULE_CAT.operands || []).find((o) => o.id === id); }
function freshOperand(id) {
  const spec = operandSpec(id);
  const o = { ind: id };
  for (const p of (spec ? spec.params : [])) o[p.key] = p.default;
  return o;
}

function loadRules(er) {
  if (!er) return;
  RULE_CAT = er.catalog;
  // Leaving the tab and coming back must not throw away rows still being edited.
  if (RULES_DIRTY) return;
  RULES = clone(er.rules || []);
  RULES_RESET = false;
  renderRules();
  showRuleText(er, "");
  $("ruleState").textContent = er.customised
    ? "saved in config.yaml"
    : "the default two conditions (not yet customised)";
}

/* One table of condition rows. Used by the Strategy tab (exit rules) and the Scanner (BUY and SELL).
   o = { tbody, addBtn, rows: () => array, catalog: () => cat,
         label: "Condition", labelLower: "condition",
         timeframes: false, reorder: false, readOnly: () => false, colspan: 6,
         paramAttr: "key", emptyHtml: "...", newRow: () => row, onChange: (rerender) => void }
   With the Strategy options the markup is exactly the one the tab has always drawn. */
function makeRuleEditor(o) {
  const label = esc(o.label || "Condition"), lower = esc(o.labelLower || "condition");
  const PA = o.paramAttr || "key";
  const cat = () => o.catalog();
  const ro = () => !!(o.readOnly && o.readOnly());
  const dis = () => (ro() ? " disabled" : "");
  const specOf = (id) => (cat().operands || []).find((x) => x.id === id);
  const fresh = (id) => {
    const spec = specOf(id);
    const out = { ind: id };
    for (const p of (spec ? spec.params : [])) out[p.key] = p.default;
    return out;
  };

  function operandCell(i, side, op) {
    const choices = cat().operands.filter((x) => side === "right" || x.left);
    const spec = specOf(op.ind) || { label: op.ind, params: [] };
    const what = side === "left" ? "indicator" : "compared with";
    const sel = `<select class="rsel" data-row="${i}" data-side="${side}"${dis()}
      aria-label="${label} ${i + 1} ${what}">
    ${choices.map((x) => `<option value="${esc(x.id)}" ${x.id === op.ind ? "selected" : ""}>${esc(x.label)}</option>`).join("")}
    </select>`;
    const params = spec.params.map((p) => `<label class="pp">${esc(p.label)}
      <input type="text" inputmode="decimal" autocomplete="off" class="rp" size="5"
        data-row="${i}" data-side="${side}" data-${PA}="${esc(p.key)}"${dis()}
        value="${esc(op[p.key] == null ? p.default : op[p.key])}"
        aria-label="${label} ${i + 1} ${esc(spec.label)} ${esc(p.label.toLowerCase())}" /></label>`).join("");
    return `<div class="opnd">${sel}${params}</div>`;
  }

  function tfCell(i, r) {
    return `<select class="rtf" data-row="${i}"${dis()} aria-label="${label} ${i + 1} timeframe">
        ${(cat().timeframes || []).map((t) => `<option value="${esc(t.id)}" ${t.id === r.tf ? "selected" : ""}>${esc(t.id)}</option>`).join("")}
      </select>`;
  }

  function candleCell(i, r) {
    const selected = r.candle_type || "normal";
    return `<select class="rct" data-row="${i}"${dis()} aria-label="${label} ${i + 1} candle type">
      ${(cat().candle_types || [{id:"normal", label:"Normal"}]).map((x) =>
        `<option value="${esc(x.id)}" ${x.id === selected ? "selected" : ""}>${esc(x.label)}</option>`).join("")}
      </select>`;
  }

  function lastCell(i, count) {
    if (ro()) return "";
    const moves = o.reorder
      ? `<button type="button" class="sm rmv" data-row="${i}" data-dir="-1" ${i === 0 ? "disabled" : ""}
            aria-label="Move ${lower} ${i + 1} up">↑</button>
         <button type="button" class="sm rmv" data-row="${i}" data-dir="1" ${i === count - 1 ? "disabled" : ""}
            aria-label="Move ${lower} ${i + 1} down">↓</button>
         ` : "";
    return `${moves}<button type="button" class="sm rdel" data-row="${i}"
            aria-label="Remove ${lower} ${i + 1}">✕</button>`;
  }

  function render() {
    const tb = o.tbody;
    if (!cat()) return;
    const RULES = o.rows();
    const C = cat();
    if (!RULES.length) {
      tb.innerHTML = o.emptyHtml;
    } else {
      tb.innerHTML = RULES.map((r, i) => `<tr>
      <td class="l">${i === 0 ? '<span class="mut">IF</span>'
        : `<select class="rjoin" data-row="${i}"${dis()} aria-label="How ${lower} ${i + 1} joins the one above">
             <option value="AND" ${r.join === "AND" ? "selected" : ""}>AND</option>
             <option value="OR" ${r.join === "OR" ? "selected" : ""}>OR</option></select>`}</td>${o.timeframes ? `
      <td class="l">${tfCell(i, r)}</td>` : ""}
      <td class="l">${candleCell(i, r)}</td>
      <td class="l">${operandCell(i, "left", r.left)}</td>
      <td class="l"><select class="rop" data-row="${i}"${dis()} aria-label="${label} ${i + 1} comparison">
        ${C.comparators.map((c) => `<option value="${esc(c.id)}" ${c.id === r.op ? "selected" : ""}>${esc(c.label)}</option>`).join("")}
      </select></td>
      <td class="l">${operandCell(i, "right", r.right)}</td>
      <td class="l"><select class="ron" data-row="${i}"${dis()} aria-label="When ${lower} ${i + 1} is checked">
        ${C.on.map((x) => `<option value="${esc(x.id)}" ${x.id === r.on ? "selected" : ""}>${esc(x.label)}</option>`).join("")}
      </select></td>
      <td>${lastCell(i, RULES.length)}</td>
    </tr>`).join("");
    }
    if (o.addBtn) {
      o.addBtn.disabled = RULES.length >= (C.max_rules || 12);
      if (o.readOnly) o.addBtn.hidden = ro();
    }
    if (ro()) return;

    const row = (el) => o.rows()[Number(el.dataset.row)];
    tb.querySelectorAll(".rsel").forEach((el) => {
      el.onchange = () => { row(el)[el.dataset.side] = fresh(el.value); o.onChange(true); };
    });
    tb.querySelectorAll(".rp").forEach((el) => {
      el.oninput = () => {
        row(el)[el.dataset.side][el.dataset[PA]] = el.value.trim();
        el.classList.toggle("bad", el.value.trim() !== "" && !Number.isFinite(Number(el.value)));
        o.onChange(false);
      };
    });
    tb.querySelectorAll(".rop").forEach((el) => { el.onchange = () => { row(el).op = el.value; o.onChange(false); }; });
    tb.querySelectorAll(".rjoin").forEach((el) => { el.onchange = () => { row(el).join = el.value; o.onChange(false); }; });
    tb.querySelectorAll(".ron").forEach((el) => { el.onchange = () => { row(el).on = el.value; o.onChange(false); }; });
    tb.querySelectorAll(".rtf").forEach((el) => { el.onchange = () => { row(el).tf = el.value; o.onChange(false); }; });
    tb.querySelectorAll(".rct").forEach((el) => { el.onchange = () => { row(el).candle_type = el.value; o.onChange(false); }; });
    tb.querySelectorAll(".rdel").forEach((el) => {
      el.onclick = () => { o.rows().splice(Number(el.dataset.row), 1); o.onChange(true); };
    });
    tb.querySelectorAll(".rmv").forEach((el) => {
      el.onclick = () => {
        const list = o.rows(), i = Number(el.dataset.row), d = Number(el.dataset.dir), j = i + d;
        if (j < 0 || j >= list.length) return;
        [list[i], list[j]] = [list[j], list[i]];
        o.onChange(true);
        // Focus stays on the same button, now on the moved row.
        const same = tb.querySelector(`.rmv[data-row="${j}"][data-dir="${d}"]`);
        const other = tb.querySelector(`.rmv[data-row="${j}"][data-dir="${-d}"]`);
        if (same && !same.disabled) same.focus(); else if (other) other.focus();
      };
    });
  }

  if (o.addBtn && o.newRow) {
    o.addBtn.onclick = () => {
      if (!cat() || ro()) return;
      o.rows().push(o.newRow(fresh));
      o.onChange(true);
    };
  }
  return { render, fresh };
}

const STRATEGY_RULES = makeRuleEditor({
  tbody: $("ruleRows"), addBtn: $("ruleAdd"), rows: () => RULES, catalog: () => RULE_CAT,
  label: "Condition", labelLower: "condition", colspan: 7,
  emptyHtml: `<tr><td colspan="7" class="l mut">No indicator conditions: positions close
      on the stop, the target or the square-off only.</td></tr>`,
  onChange: (rerender) => rulesChanged(rerender),
});
function renderRules() { STRATEGY_RULES.render(); }

function rulesChanged(rerender) {
  RULES_DIRTY = true;
  RULES_RESET = false;
  if (rerender) renderRules();
  $("ruleState").textContent = "unsaved changes: press Save settings at the bottom";
  clearTimeout(RULE_TIMER);
  RULE_TIMER = setTimeout(previewRules, 350);
}

async function previewRules() {
  try {
    const d = await api("/api/strategy/exit-rules/preview", { method: "POST",
      body: JSON.stringify({ rules: RULES_RESET ? null : RULES }) });
    showRuleText(d, "");
  } catch (e) { showRuleText(null, e.message); }
}

function showRuleText(d, err) {
  const box = $("ruleText");
  if (err) { box.className = "rulebox bad"; box.textContent = err; return; }
  box.className = "rulebox";
  box.innerHTML = `<div><strong>A long closes when</strong> ${esc(d.long)}</div>
    <div><strong>A short closes when</strong> ${esc(d.short)}
      <span class="mut">(the mirror image: above ↔ below, RSI levels reflected around 50;
      ADX and ATR stay as written)</span></div>
    ${d.warmup_bars ? `<div class="mut">These need ${d.warmup_bars} candles of history on the
      watch's timeframe; entries wait until that much is available.</div>` : ""}`;
}

$("ruleAdd").onclick = () => {
  if (!RULE_CAT) return;
  RULES.push({ join: "OR", left: freshOperand("close"), op: "below",
               right: freshOperand("vwap"), on: "close", candle_type: "normal" });
  rulesChanged(true);
};
$("ruleDefault").onclick = async () => {
  if (!confirm("Replace these rows with the default two conditions?")) return;
  try {
    const d = await api("/api/strategy/exit-rules/preview", { method: "POST",
      body: JSON.stringify({ rules: null }) });
    RULES = clone(d.rules);
    RULES_DIRTY = true;
    RULES_RESET = true;
    renderRules();
    showRuleText(d, "");
    $("ruleState").textContent = "default rows: press Save settings at the bottom to apply";
  } catch (e) { note(e.message); }
};

$("btnReloadStrat").onclick = () => { RULES_DIRTY = false; loadSettings(); };
$("btnSaveStrat").onclick = async () => {
  const patch = { strategy:{}, risk:{}, engine:{} };
  document.querySelectorAll("[data-sec]").forEach((el) => {
    const sec = el.dataset.sec, key = el.dataset.key;
    if (el.type === "checkbox") { patch[sec][key] = el.checked; return; }
    const raw = el.value.trim();
    if (el.type === "number" || el.dataset.num) patch[sec][key] = raw === "" ? null : Number(raw);
    else patch[sec][key] = raw;
  });
  // Rows go only when touched, so saving other settings never freezes the defaults.
  if (RULES_DIRTY) patch.strategy.exit_rules = RULES_RESET ? null : RULES;
  try {
    await api("/api/settings/config", { method:"PUT", body: JSON.stringify(patch) });
    note("Settings saved to config.yaml.", "ok");
    RULES_DIRTY = false;
    loadSettings(); refresh();
  } catch (e) { note(e.message); }
};

/* ----------------------------------------------------------- order dialog */
/* Market or limit, the product, and what closes the trade: for the Trade tab's Buy /
   Sell, the Options tab's Buy and a basket's Execute. Resolves with the choices to send
   (order_type, limit_price or limit_prices, product, exit_mode), or null if cancelled. */
let ORD = null;   // { resolve, opts } while the dialog is open
const roundTick = (v, tick) => {
  const t = Number(tick) > 0 ? Number(tick) : 0.05;
  return (Math.round(Number(v) / t) * t).toFixed(t < 0.01 ? 4 : 2);
};
const ordType = () => document.querySelector('input[name="ordType"]:checked').value;

function orderDialog(opts) {
  return new Promise((resolve) => {
    if (ORD) { const prev = ORD.resolve; ORD = null; prev(null); }
    ORD = { resolve, opts };
    const live = SETTINGS_MODE === "live";
    $("ordTitle").textContent = opts.title;
    $("ordSub").textContent = opts.sub || "";
    $("ordMode").className = "mode " + (live ? "live" : "paper");
    $("ordMode").textContent = live ? "LIVE · this sends REAL orders to your broker"
                                    : "PAPER · orders are simulated";
    $("ordMkt").checked = true;
    const tick = opts.tick || 0.05;
    $("ordLimit").step = String(tick);
    $("ordLimit").value = opts.ltp ? roundTick(opts.ltp, tick) : "";
    $("ordLegsWrap").hidden = !opts.legs;
    $("ordLegs").innerHTML = (opts.legs || []).map((l, i) => `<tr>
        <td class="l">${esc(l.label)}</td>
        <td class="l ${l.side === "SELL" ? "down" : "up"}">${esc(l.side)}</td>
        <td>${l.quantity}</td><td>${n(l.ltp)}</td>
        <td class="limcell"><input class="lim" type="number" min="0" step="0.05" inputmode="decimal"
          data-leg="${i}" value="${l.ltp ? roundTick(l.ltp, 0.05) : ""}"
          aria-label="Limit price for ${esc(l.label)}" /></td></tr>`).join("");
    $("ordProduct").value = opts.product === "DELIVERY" ? "DELIVERY" : "INTRADAY";
    $("ordExit").value = ["both", "sl_target", "strategy"].includes(opts.exitMode) ? opts.exitMode : "both";
    $("ordErr").textContent = "";
    updateOrder();
    $("ord").showModal();
    $("ordMkt").focus();
  });
}

function orderProblem(o, limit, product, exitMode) {
  if (o.cashShort && product === "DELIVERY") {
    return "Shares sold short cannot be carried as delivery; choose Intraday.";
  }
  if (exitMode === "strategy" && !HAS_RULES) {
    return "No exit conditions are set on the Strategy tab, so nothing would close this trade.";
  }
  if (limit && !o.legs && !(Number($("ordLimit").value) > 0)) return "Enter a limit price.";
  return "";
}

function updateOrder() {
  if (!ORD) return;
  const o = ORD.opts, limit = ordType() === "LIMIT";
  const product = $("ordProduct").value, exitMode = $("ordExit").value;
  $("ordLimitWrap").hidden = !limit || !!o.legs;
  $("ordLegLimitHead").hidden = !limit;
  $("ordLegs").querySelectorAll(".limcell").forEach((td) => { td.hidden = !limit; });
  const hints = [];
  if (limit && !o.legs) {
    const v = Number($("ordLimit").value);
    if (v > 0 && o.ltp > 0) {
      const resting = o.side === "SELL" ? v > o.ltp : v < o.ltp;
      hints.push(resting ? `Rests at the broker until the price comes to ${n(v)}.`
                         : `At or through the market (${n(o.ltp)}): fills now.`);
    }
  }
  if (limit) {
    hints.push(product === "DELIVERY" ? "An unfilled limit is cancelled at the close."
      : `An unfilled limit is cancelled at the no-new-entry cutoff (${RISK.no_new_entry_after || "15:00"}).`);
    if (o.legs) hints.push("Each leg fills when its own price comes, so the legs can fill at different times.");
  }
  hints.push(product === "DELIVERY" ? "Delivery: carried overnight, never squared off."
    : `Intraday: squared off at ${RISK.square_off_time || "15:15"}.`);
  hints.push(exitMode === "strategy"
    ? '<span class="down">No stop loss: only the exit conditions close it.</span>'
    : exitMode === "sl_target" ? "Closes on the stop, trailing stop or target only."
    : "Closes on the stop, trailing stop, target or the exit conditions, whichever comes first.");
  $("ordHint").innerHTML = hints.map((h) => `<span>${h}</span>`).join("");
  $("ordErr").textContent = orderProblem(o, limit, product, exitMode);
  $("ordOk").textContent = (limit ? "Place limit " : "Place market ") + (o.legs ? "orders" : (o.side || "order"));
  $("ordOk").className = o.side === "SELL" && !o.legs ? "danger" : "go";
}
$("ordForm").addEventListener("change", updateOrder);
$("ordForm").addEventListener("input", updateOrder);
$("ordCancel").onclick = () => $("ord").close();
$("ord").addEventListener("close", () => {
  if (ORD) { const r = ORD.resolve; ORD = null; r(null); }
});
$("ordForm").onsubmit = (ev) => {
  ev.preventDefault();
  if (!ORD) return;
  const o = ORD.opts, limit = ordType() === "LIMIT";
  const out = { order_type: limit ? "LIMIT" : "MARKET", product: $("ordProduct").value,
                exit_mode: $("ordExit").value };
  const problem = orderProblem(o, limit, out.product, out.exit_mode);
  if (problem) { $("ordErr").textContent = problem; return; }
  if (limit && !o.legs) out.limit_price = Number($("ordLimit").value);
  if (limit && o.legs) {
    out.limit_prices = {};
    for (const el of $("ordLegs").querySelectorAll("input.lim")) {
      const v = Number(el.value), leg = o.legs[Number(el.dataset.leg)];
      if (!(v > 0)) { $("ordErr").textContent = `Enter a limit price for ${leg.label}.`; el.focus(); return; }
      out.limit_prices[leg.symbol] = v;
    }
  }
  if (SETTINGS_MODE === "live" && !confirm(`LIVE — REAL MONEY\n\n${o.title}\n` +
      `${limit ? "Limit" : "Market"} · ${out.product.toLowerCase()} · ${EXIT_TEXT[out.exit_mode]}` +
      (o.confirmWarning ? `\n\n${o.confirmWarning}` : "") + "\n\nSend it?")) return;
  const r = ORD.resolve;
  ORD = null;
  $("ord").close();
  r(out);
};

/* ------------------------------------------------------------------ trade */
$("addForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const body = {
    symbol: $("sym").value.trim().toUpperCase(),
    exchange: $("exch").value,
    direction: $("dir").value,
    quantity: Number($("qty").value),
    timeframe_minutes: Number($("tf").value),
    candle_type: $("tradeCandle").value,
    stop_loss_pct: Number($("sl").value) || null,
    target_pct: $("tp").value ? Number($("tp").value) : null,
    product: $("prod").value || null,
    exit_mode: $("exm").value || null,
  };
  try {
    await api("/api/watches", { method:"POST", body: JSON.stringify(body) });
    const how = {
      LONG: "It asks for approval to BUY when price is above Advanced VWAP, RSI above its 21-EMA and price above Supertrend.",
      SHORT: "It asks for approval to SELL when price is below Advanced VWAP, RSI below its 21-EMA and price below Supertrend.",
      BOTH: "It asks to BUY when the long conditions line up and to SELL when their mirror image does — one position at a time.",
    }[body.direction];
    note(`${body.symbol} added ${body.direction}. ${how}`, "ok");
    $("sym").value = "";
    loadTrade();
  } catch (e) { note(e.message); }
};

async function loadTrade() {
  try { renderAppr((await api("/api/approvals")).approvals || []); } catch (e) {}
  try { renderWatches((await api("/api/watches")).watches || []); } catch (e) {}
}

function renderAppr(list) {
  $("apprN").textContent = list.length ? "(" + list.length + ")" : "";
  const box = $("appr");
  if (!list.length) { box.innerHTML = '<p class="mut">Nothing waiting.</p>'; return; }
  box.innerHTML = list.map((a) => {
    const s = a.snapshot || {};
    const checks = Object.entries(a.checks || {}).map(([k, v]) =>
      `<span class="chk ${v ? "yes" : "no2"}">${v ? "✓" : "✗"} ${esc(k.replace(/_/g," "))}</span>`).join(" &nbsp; ");
    const side = a.side || sideOf(a.direction);
    return `<div class="card">
      <h3>${esc(a.instrument.symbol || a.instrument.display_name)} —
        <span class="${side === "SELL" ? "down" : "up"}">${side}</span> ${a.quantity}
        <span class="mut" style="font-weight:400">(${side === "SELL" ? "short: sell to open, buy back to close" : "long: buy to open, sell to close"})</span></h3>
      <div class="kv">
        <span>Ref price <strong>${n(a.reference_price)}</strong></span>
        <span>Capital <strong>₹${n(a.capital_deployed)}</strong></span>
        ${a.exit_mode === "strategy"
          ? `<span>Stop <strong class="down">none</strong> <span class="mut">exit conditions only</span></span>
             <span>Risk <strong>not capped</strong></span>`
          : `<span>Stop <strong>${n(a.stop_price)}</strong> <span class="mut">${side === "SELL" ? "above" : "below"} entry</span></span>
             <span>Risk <strong>₹${n(a.risk_amount)}</strong></span>
             <span>Target <strong>${a.target_price ? n(a.target_price) : "none"}</strong></span>`}
        <span>Product <strong>${a.product === "DELIVERY" ? "delivery" : "intraday"}</strong></span>
        <span>Exit <strong>${esc(EXIT_TEXT[a.exit_mode] || EXIT_TEXT.both)}</strong></span>
        <span>Advanced VWAP ${n(s.vwap)}</span>
        <span>RSI ${n(s.rsi)} vs ${n(s.rsi_signal_entry)}</span>
        <span>Supertrend ${n(s.supertrend)}</span>
        <span>ADX ${n(s.adx)}</span>
        <span>Candle ${clock(s.candle_ts)}</span>
        <span>Expires ${clock(a.expires_at)}</span>
      </div>
      <p style="margin:7px 0">${checks}</p>
      <div class="row">
        <button type="button" class="go" data-ok="${esc(a.id)}" data-side="${side}">Approve &amp; ${side === "SELL" ? "sell" : "buy"}</button>
        <button type="button" class="danger" data-no="${esc(a.id)}">Reject</button>
      </div></div>`;
  }).join("");

  box.querySelectorAll("[data-ok]").forEach((b) => {
    b.onclick = async () => {
      const live = SETTINGS_MODE === "live";
      if (!confirm((live ? "LIVE — REAL MONEY\n\n" : "Paper mode (simulated)\n\n") +
          `Send the ${b.dataset.side} order now?`)) return;
      b.disabled = true;
      try { await api("/api/approvals/" + b.dataset.ok + "/approve", { method:"POST" });
        note("Order sent.", "ok"); } catch (e) { note(e.message); }
      loadTrade();
    };
  });
  box.querySelectorAll("[data-no]").forEach((b) => {
    b.onclick = async () => {
      b.disabled = true;
      try { await api("/api/approvals/" + b.dataset.no + "/reject",
        { method:"POST", body: JSON.stringify({ note:"rejected from console" }) }); }
      catch (e) { note(e.message); }
      loadTrade();
    };
  });
}

/* Buy and/or Sell buttons, depending on which sides the watch may trade. */
function entryButtons(w) {
  const sides = w.sides === "BOTH" ? ["LONG", "SHORT"] : [w.sides || w.direction || "LONG"];
  return sides.map((dir) => {
    const side = sideOf(dir);
    return `<button type="button" class="sm ${dir === "SHORT" ? "danger" : "go"}"
      data-buy="${esc(w.id)}" data-dir="${dir}"
      title="${side === "SELL" ? "Sell to open" : "Buy to open"} now, skipping the signal"
      >${side === "SELL" ? "Sell" : "Buy"}</button> `;
  }).join("");
}

/* Whether every entry condition holds on the last closed candle, as on the Options tab.
   The tooltip lists each condition, why it fails, and when it was last checked. */
const LIVE_STATES = ["entry_placed", "in_position", "exit_placed", "gtt_pending"];
function readiness(w) {
  const sig = w.last_signal;
  if (w.position || LIVE_STATES.includes(w.state) || !sig) return null;
  const checks = Object.entries(sig.checks || {});
  const passed = checks.filter(([, v]) => v).length;
  const side = w.sides === "BOTH" && w.signal_side ? sideOf(w.signal_side) : "";
  const tip = [
    side ? `${side} side (the one price favours now)` : "",
    ...checks.map(([k, v]) => `${v ? "✓" : "✗"} ${k.replace(/_/g, " ")}`),
    ...(sig.reasons || []).filter((x) => !x.startsWith("all entry")).map((x) => "· " + x),
    w.signal_at ? `checked ${clock(w.signal_at)}` : "",
  ].filter(Boolean).join("\n");
  return { ready: !!sig.ready, passed, total: checks.length, side, tip };
}
function readyCell(w) {
  if (w.position || LIVE_STATES.includes(w.state)) {
    return `<td class="mut" title="Entry conditions are checked while the watch waits for an entry">—</td>`;
  }
  const r = readiness(w);
  if (!r) return `<td class="mut" title="Not checked yet: it is evaluated on the next engine poll">…</td>`;
  if (r.ready) return `<td class="rdy" title="${esc(r.tip)}">READY${r.side ? " " + r.side : ""}</td>`;
  return `<td class="mut" title="${esc(r.tip)}">no · ${r.passed}/${r.total}</td>`;
}
function stopCell(p) {
  if (!p) return "—";
  if (p.exit_mode === "strategy") {
    return `<span class="mut" title="No stop: this position exits on its conditions only">none</span>`;
  }
  const trail = p.trail_value
    ? `<span class="tagb" title="${p.trail_trigger_pct
        ? `Trailing profit: once ${esc(p.trail_trigger_pct)}% in profit, ${esc(p.trail_value)}${p.trail_unit === "pct" ? "%" : " pts"} behind the best price${p.trail_active ? " (active)" : " (waiting)"}`
        : `Trailing ${esc(p.trail_value)}${p.trail_unit === "pct" ? "%" : " pts"} behind the best price`}">${
        p.trail_trigger_pct ? (p.trail_active ? "trail on" : "trail @" + esc(p.trail_trigger_pct) + "%") : "trail"}</span>`
    : "";
  return n(p.stop_price) + trail;
}
function tradeTags(w) {
  const p = w.position;
  const product = p ? p.product : w.product;
  const mode = p ? p.exit_mode : (w.effective_exit_mode || w.exit_mode || "both");
  let html = "";
  if (product === "DELIVERY") html += '<span class="tagb" title="Carried overnight: CNC / NRML, never squared off">delivery</span>';
  if (mode && mode !== "both") html += `<span class="tagb" title="Closes on ${esc(EXIT_TEXT[mode])}">${mode === "strategy" ? "rules only" : "SL/TP only"}</span>`;
  return html;
}

function renderWatches(list) {
  const tb = $("watches");
  if (!list.length) { tb.innerHTML = '<tr><td colspan="19" class="mut">No watches yet.</td></tr>'; return; }
  tb.innerHTML = list.map((w) => {
    const s = (w.last_signal && w.last_signal.snapshot) || {};
    const p = w.position;
    const pnl = p ? p.unrealised_pnl : null;
    const stc = s.supertrend_direction === -1 ? "up" : (s.supertrend_direction === 1 ? "down" : "mut");
    const ready = readiness(w);
    return `<tr class="${ready && ready.ready ? "ready" : ""}">
      <td class="l">${esc(instName(w.instrument))}</td>
      ${w.sides === "BOTH"
        ? `<td class="l" title="Takes whichever side signals">${p
            ? `<span class="${w.direction === "SHORT" ? "down" : "up"}">${esc(w.direction)}</span> <span class="mut">(both)</span>`
            : "BOTH"}</td>`
        : dirCell(p ? w.direction : (w.sides || w.direction))}
      <td class="l">${esc(w.kind)}${w.basket_id ? '<span class="tagb" title="Leg of a basket; enter and exit it from the Baskets tab">basket</span>' : ""}${tradeTags(w)}</td>
      <td>${esc(tfCode(w.timeframe_minutes))}</td>
      <td>${w.candle_type === "heikin_ashi" ? "Heikin Ashi" : "Normal"}</td><td>${w.quantity}</td>
      <td class="l">${esc(w.state.replace(/_/g," "))}</td>
      <td>${n(p ? p.ltp : (w.ltp != null ? w.ltp : s.ltp))}</td><td>${n(s.vwap)}</td><td>${n(s.rsi)}</td>
      <td>${n(s.rsi_signal_entry)}</td><td class="${stc}">${n(s.supertrend)}</td><td>${n(s.adx)}</td>
      ${readyCell(w)}
      <td>${p ? n(p.entry_price) : "—"}</td>
      <td>${stopCell(p)}</td>
      <td class="${pnl > 0 ? "up" : pnl < 0 ? "down" : "mut"}">${pnl === null ? "—" : n(pnl)}</td>
      <td class="l mut" title="${esc(w.last_error || w.notes)}">${esc((w.last_error || w.notes || "").slice(0,40))}</td>
      <td style="white-space:nowrap">
        <button type="button" class="sm" data-chart="${esc(w.id)}">Chart</button>
        ${p
          ? `<button type="button" class="sm danger" data-exit="${esc(w.id)}"
               ${w.state === "exit_placed" ? "disabled" : ""}>Exit</button>`
          : (w.state === "gtt_pending" || w.state === "entry_placed")
            ? `<button type="button" class="sm danger" data-cancel="${esc(w.id)}"
                 title="${esc(w.ticket ? w.ticket.text : "Cancel the working entry order")}">Cancel order</button>`
            : w.basket_id
              ? ""
              : entryButtons(w) + `<button type="button" class="sm" data-del="${esc(w.id)}">Remove</button>`}
      </td>
    </tr>`;
  }).join("");

  tb.querySelectorAll("[data-cancel]").forEach((b) => {
    b.onclick = async () => {
      const w = list.find((x) => x.id === b.dataset.cancel);
      const what = w && w.state === "gtt_pending" ? "the pending GTT order" : "the working entry order";
      if (!confirm(`Cancel ${what}${w ? " on " + instName(w.instrument) : ""}?`)) return;
      b.disabled = true;
      try {
        await api(`/api/watches/${b.dataset.cancel}/cancel`, { method: "POST" });
        note("Order cancelled.", "ok");
      } catch (e) { note(e.message); }
      loadTrade();
    };
  });

  tb.querySelectorAll("[data-chart]").forEach((b) => {
    b.onclick = () => {
      const w = list.find((x) => x.id === b.dataset.chart);
      if (!w) return;
      const syms = [chartSymbolFor(w.instrument)];
      // An option is only meaningful next to what drives it.
      if (w.kind === "option" && w.instrument.underlying) {
        syms.push(`fut:${w.instrument.underlying}`);
      }
      openCharts(syms, tfCode(w.timeframe_minutes));
    };
  });

  tb.querySelectorAll("[data-buy]").forEach((b) => {
    b.onclick = async () => {
      const w = list.find((x) => x.id === b.dataset.buy);
      if (!w) return;
      const dir = b.dataset.dir;
      const side = sideOf(dir);
      const stopSide = dir === "SHORT" ? "above" : "below";
      const ltp = w.ltp != null ? w.ltp : ((w.last_signal && w.last_signal.snapshot) || {}).ltp;
      const choice = await orderDialog({
        title: `${side} ${w.quantity} × ${instName(w.instrument)}`,
        sub: `LTP ${n(ltp)} · skips the signal · stop ${w.stop_loss_pct}% ${stopSide} the entry` +
          (w.target_pct ? ` · target ${w.target_pct}%` : ""),
        side, ltp, tick: w.instrument.tick_size,
        product: w.product, exitMode: w.effective_exit_mode || w.exit_mode || RISK.exit_mode,
        cashShort: dir === "SHORT" && isCash(w.instrument),
      });
      if (!choice) return;
      b.disabled = true;
      try {
        const r = await api(`/api/watches/${w.id}/enter`, {
          method: "POST", body: JSON.stringify({ confirm: true, direction: dir, ...choice }) });
        const p = r.watch && r.watch.position;
        note(p
          ? `${side} filled at ${n(p.entry_price)}` + (p.exit_mode === "strategy"
              ? " — no stop: it closes on the exit conditions" : ` — stop at ${n(p.stop_price)}`) + "."
          : `${side} limit order working at ${n(choice.limit_price)}; it fills when the price comes to it.`, "ok");
      } catch (e) { note(e.message); }
      loadTrade();
    };
  });
  tb.querySelectorAll("[data-exit]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Exit this position at market?")) return;
      try { await api("/api/watches/" + b.dataset.exit + "/exit", { method:"POST" });
        note("Exit order sent.", "ok"); } catch (e) { note(e.message); }
      loadTrade();
    };
  });
  tb.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = async () => {
      try { await api("/api/watches/" + b.dataset.del, { method:"DELETE" }); }
      catch (e) { note(e.message); }
      loadTrade();
    };
  });
}

/* ---------------------------------------------------------------- options */
const OPTION_TABS = ["scan", "straddle"];
function showOptionTab(name) {
  OPTION_TABS.forEach((tab) => {
    const button = $("opt-tab-" + tab), panel = $("opt-panel-" + tab);
    const selected = tab === name;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    button.tabIndex = selected ? 0 : -1;
    button.classList.toggle("go", selected);
    panel.hidden = !selected;
  });
  if (name === "straddle") loadStraddleExpiries();
}
OPTION_TABS.forEach((tab, index) => {
  const button = $("opt-tab-" + tab);
  button.onclick = () => showOptionTab(tab);
  button.onkeydown = (ev) => {
    if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
    ev.preventDefault();
    const next = OPTION_TABS[
      (index + (ev.key === "ArrowRight" ? 1 : OPTION_TABS.length - 1)) % OPTION_TABS.length
    ];
    showOptionTab(next); $("opt-tab-" + next).focus();
  };
});

async function loadExpiries() {
  try {
    const d = await api("/api/options/expiries?underlying=" + encodeURIComponent($("und").value));
    $("exp").innerHTML = '<option value="">nearest</option>' +
      (d.expiries || []).slice(0, 12).map((e) => `<option value="${esc(e)}">${esc(e)}</option>`).join("");
  } catch (e) { /* not fatal: nearest still works */ }
}

async function loadStraddleExpiries() {
  const select = $("strExp"), selected = select.value;
  try {
    const d = await api("/api/options/expiries?underlying=" + encodeURIComponent($("strUnd").value));
    const expiries = d.active || d.expiries || [];
    select.innerHTML = '<option value="">nearest</option>' +
      expiries.slice(0, 12).map((e) => `<option value="${esc(e)}">${esc(e)}</option>`).join("");
    if (expiries.includes(selected)) select.value = selected;
  } catch (e) { /* not fatal: nearest still works */ }
}
$("strUnd").onchange = loadStraddleExpiries;
$("straddleForm").onsubmit = (ev) => { ev.preventDefault(); loadStraddles(); };

async function loadStraddles() {
  const q = new URLSearchParams({
    underlying: $("strUnd").value,
    timeframe_minutes: $("strTf").value,
    candle_type: $("strCandle").value,
  });
  if ($("strExp").value) q.set("expiry", $("strExp").value);
  $("btnStraddle").disabled = true;
  $("straddleMeta").textContent = "";
  $("straddleRows").innerHTML = '<tr><td colspan="13" class="mut">Scanning 15 straddles…</td></tr>';
  try {
    const d = await api("/api/options/straddles?" + q.toString());
    STRADDLE_DATA = d;
    const rows = d.rows || [];
    const incomplete = rows.filter((row) => row.error).length;
    const shortage = Math.max(0, Number(d.requested_rows || 15) - rows.length);
    $("straddleMeta").textContent =
      d.underlying + " " + d.expiry + " · spot " + n(d.spot) + " · ATM " + n(d.atm_strike, 0) +
      " · " + tfCode(d.timeframe_minutes) + " · " +
      (d.candle_type === "heikin_ashi" ? "Heikin Ashi" : "Normal candle") + " · " +
      rows.length + "/" + (d.requested_rows || 15) +
      " strikes · closed candle " + clock(d.as_of) +
      (d.expires_today ? " · EXPIRES TODAY" : "") +
      (shortage ? " · " + shortage + " boundary strike(s) unavailable" : "") +
      (incomplete ? " · " + incomplete + " incomplete row(s)" : "");
    renderStraddles(d);
  } catch (e) {
    STRADDLE_DATA = null;
    note(e.message);
    $("straddleRows").innerHTML = '<tr><td colspan="13" class="down"></td></tr>';
    $("straddleRows").querySelector("td").textContent = e.message;
  } finally { $("btnStraddle").disabled = false; }
}

function straddleStateClass(value) {
  if (value === "above" || value === "positive" || value === "BUY") return "up";
  if (value === "below" || value === "negative" || value === "SELL") return "down";
  return "mut";
}
function straddleIndicator(value, relation, label) {
  const rel = relation ? ` <span class="${straddleStateClass(relation)}">${esc(relation)}</span>` : "";
  const title = relation ? `${label}: current displayed straddle price is ${relation}` : `${label} unavailable`;
  return `<span title="${esc(title)}">${n(value)}${rel}</span>`;
}
function renderStraddles(d) {
  const rows = d.rows || [];
  const body = $("straddleRows");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="13" class="mut">No strikes available.</td></tr>';
    return;
  }
  const quoteSource = (source) => ({
    broker_ltp: "direct broker quote",
    provider_ltp_display_only: "provider LTP fallback (display only)",
    synthetic_paper_price: "synthetic paper price",
    latest_candle_close: "latest candle fallback (display only)",
    closed_candle_close: "closed candle fallback (display only)",
    missing: "unavailable",
  }[source] || "unknown source");
  const executionSource = (source) => ({
    direct_broker_quote: "execution-eligible direct quote",
    paper_reference: "paper reference (simulated execution-eligible only)",
    unavailable: "not execution-eligible",
  }[source] || "not execution-eligible");
  const legPriceTitle = (label, price, quote, execution) =>
    `${label} ${n(price)} (${quoteSource(quote)}; ${executionSource(execution)})`;
  body.innerHTML = rows.map((row, index) => {
    const move = row.change_price > 0 ? "up" : row.change_price < 0 ? "down" : "mut";
    const percent = row.change_pct == null ? "—" : n(row.change_pct) + "%";
    const warning = row.error ? ` <span class="down" title="${esc(row.error)}">⚠</span>` : "";
    const atm = row.atm ? ' <span class="tagb">ATM</span>' : "";
    const canonical = !!(row.ce && row.pe && row.ce.chart_symbol && row.pe.chart_symbol);
    const comboAttrs = canonical
      ? ' title="Open the canonical CE + PE combo chart"'
      : ' disabled title="Both canonical CE and PE contracts are required"';
    const status = ["BUY", "SELL", "AVOID"].includes(row.status) ? row.status : "AVOID";
    const tradeReady = canonical && row.trade_ready === true && status !== "AVOID";
    const tradeReason = row.trade_unavailable_reason || (status === "AVOID"
      ? "Status is AVOID; trading is disabled" : "This row is not trade-ready");
    const tradePriceDescription = row.execution_price_source === "paper_reference"
      ? "positive paper reference price(s) for simulated execution and current closed-candle indicators"
      : "both legs have direct broker quotes and current closed-candle indicators";
    const tradeAttrs = (wanted) => tradeReady && status === wanted
      ? ` title="Trade-ready ${esc(status)} row: ${esc(tradePriceDescription)}"`
      : ` disabled title="${esc(tradeReady ? `Status is ${status}; only ${status} is enabled` : tradeReason)}"`;
    const priceTitle = legPriceTitle(
      "CE", row.ce_ltp, row.ce_quote_source, row.ce_execution_price_source
    ) + " + " + legPriceTitle(
      "PE", row.pe_ltp, row.pe_quote_source, row.pe_execution_price_source
    );
    return `<tr${row.atm ? ' class="str-atm"' : ""} title="${esc(row.error)}">
      <td class="l"><strong>${esc(Number(row.strike).toString())}</strong>${atm}${warning}</td>
      <td title="${esc(priceTitle)}">${n(row.straddle_price)}</td>
      <td class="${move}" title="Previous close ${n(row.previous_close)}">${n(row.change_price)}</td>
      <td class="${move}">${percent}</td>
      <td>${n(row.close)}</td><td>${n(row.open)}</td><td>${n(row.high)}</td><td>${n(row.low)}</td>
      <td>${straddleIndicator(row.vwap, row.vwap_position, "Advanced VWAP")}</td>
      <td>${straddleIndicator(row.supertrend, row.supertrend_position, "Supertrend")}</td>
      <td>${straddleIndicator(row.ema_21, row.ema_21_position, "EMA(21)")}</td>
      <td class="${straddleStateClass(status)}"><strong>${esc(status)}</strong></td>
      <td class="l" style="white-space:nowrap">
        <button type="button" class="sm strCombo" data-str-row="${index}"${comboAttrs}>Combo chart</button>
        <button type="button" class="sm go strTrade" data-str-row="${index}" data-str-dir="LONG"${tradeAttrs("BUY")}>Buy</button>
        <button type="button" class="sm danger strTrade" data-str-row="${index}" data-str-dir="SHORT"${tradeAttrs("SELL")}>Sell</button>
      </td>
    </tr>`;
  }).join("");
  body.querySelectorAll(".strCombo").forEach((button) => {
    button.onclick = () => {
      const row = rows[Number(button.dataset.strRow)];
      if (!row || !row.ce || !row.pe) return;
      const lots = Math.max(1, Math.floor(Number($("strLots").value) || 1));
      const legs = [row.ce, row.pe].map((leg) => `${leg.chart_symbol}@BUY@${lots}`).join(",");
      window.open("/combo?" + new URLSearchParams({ legs, tf: tfCode(d.timeframe_minutes) }),
                  "matheranCombo");
    };
  });
  body.querySelectorAll(".strTrade").forEach((button) => {
    button.onclick = () => {
      const row = rows[Number(button.dataset.strRow)];
      const wanted = button.dataset.strDir === "SHORT" ? "SELL" : "BUY";
      if (!row || row.trade_ready !== true || row.status !== wanted) {
        note((row && row.trade_unavailable_reason) || `Status is ${row && row.status || "AVOID"}; only ${wanted} rows can use this action.`);
        return;
      }
      tradeStraddle(row, button.dataset.strDir, d, button);
    };
  });
}

async function tradeStraddle(row, direction, data, button) {
  const wanted = direction === "SHORT" ? "SELL" : "BUY";
  if (!row || !row.ce || !row.pe || row.trade_ready !== true || row.status !== wanted) {
    note((row && row.trade_unavailable_reason) || `Status is ${row && row.status || "AVOID"}; only ${wanted} rows can use this action.`);
    return;
  }
  const lots = Math.max(1, Math.floor(Number($("strLots").value) || 1));
  const side = direction === "SHORT" ? "SELL" : "BUY";
  const legs = [
    { symbol: row.ce.chart_symbol, label: row.ce.display_name || row.ce.symbol,
      side, quantity: lots * Math.max(1, Number(row.ce.lot_size) || 1), ltp: row.ce_ltp },
    { symbol: row.pe.chart_symbol, label: row.pe.display_name || row.pe.symbol,
      side, quantity: lots * Math.max(1, Number(row.pe.lot_size) || 1), ltp: row.pe_ltp },
  ];
  const name = `${data.underlying} ${Number(row.strike)} straddle ${side.toLowerCase()}`;
  const rollbackWarning = "Legs are submitted sequentially because the broker has no atomic " +
    "multi-leg order. If a leg fails, rollback is attempted for every leg already sent. " +
    "If rollback fails or remains in flight, residual exposure requires immediate operator action.";
  const choice = await orderDialog({
    title: `${side} ${data.underlying} ${Number(row.strike)} straddle`,
    sub: rollbackWarning + ` Each leg uses ${lots} lot${lots === 1 ? "" : "s"} and its configured protective exits.`,
    confirmWarning: rollbackWarning,
    legs, side, product: RISK.default_product, exitMode: RISK.exit_mode, cashShort: false,
  });
  if (!choice) return;
  button.disabled = true;
  let basket = null;
  try {
    basket = await api("/api/baskets", { method: "POST", body: JSON.stringify({
      name, timeframe_minutes: Number(data.timeframe_minutes),
      legs: [row.ce, row.pe].map((leg) => ({ symbol: leg.chart_symbol, direction, lots })),
      stop_loss_pct: null, target_pct: null, product: choice.product, exit_mode: choice.exit_mode,
    }) });
    const result = await api(`/api/baskets/${basket.id}/execute`, { method: "POST",
      body: JSON.stringify({
        confirm: true,
        rollback_on_failure: true,
        ...choice,
        straddle_guard: {
          underlying: data.underlying,
          expiry: data.expiry,
          strike: Number(row.strike),
          timeframe_minutes: Number(data.timeframe_minutes),
          candle_type: data.candle_type || "normal",
          side: direction,
        },
      }) });
    const failed = (result.legs || []).filter((leg) => leg.status === "failed");
    const skipped = (result.legs || []).filter((leg) => leg.status === "skipped");
    const rollback = result.rollback || {};
    const cause = failed.map((leg) => `${leg.label || leg.symbol}: ${leg.error}`).join("; ");
    if (rollback.triggered && rollback.residual_exposure) {
      const residual = (rollback.results || []).filter((item) => item.residual_exposure)
        .map((item) => `${item.label || item.symbol}: ${item.detail || item.status}`).join("; ");
      note(`${rollback.error || rollback.warning || "CRITICAL — residual partial exposure remains."} ` +
        `${result.sent} leg${result.sent === 1 ? " was" : "s were"} acknowledged as sent; ${rollback.compensated || 0} confirmed compensated. ` +
        `${cause}${residual ? "; " + residual : ""} Open Trade/Baskets now.`);
    } else if (rollback.triggered && rollback.attempted) {
      note(`COMPENSATED — sequential straddle submission stopped after a leg failed; ` +
        `${rollback.compensated} previously sent leg${rollback.compensated === 1 ? " is" : "s are"} confirmed flat. ` +
        `${cause}${skipped.length ? `; ${skipped.length} later leg(s) were not sent` : ""}.`);
    } else if (rollback.triggered) {
      note(`No partial exposure: the first leg failed and no later leg was sent. ${cause}`);
    } else if (failed.length || skipped.length) {
      note(`${result.sent} of ${result.legs.length} legs sent. ` +
        [...failed, ...skipped].map((leg) => `${leg.label || leg.symbol}: ${leg.error}`).join("; "));
    } else {
      note(`${side} straddle basket executed sequentially: ${result.sent} ${result.order_type === "LIMIT" ? "limit orders working" : "orders sent"} ` +
        `(${result.mode}, ${String(result.product || "").toLowerCase()}).`, "ok");
    }
  } catch (e) { note(e.message); }
  if (basket) {
    loadTrade();
    loadBaskets();
  }
  button.disabled = row.trade_ready !== true || row.status !== wanted;
}
$("und").onchange = loadExpiries;
$("autoScan").onchange = () => {
  if (SCAN_TIMER) { clearInterval(SCAN_TIMER); SCAN_TIMER = null; }
  if ($("autoScan").checked) SCAN_TIMER = setInterval(scan, 20000);
};
$("chainForm").onsubmit = (ev) => { ev.preventDefault(); scan(); };

async function scan() {
  const q = new URLSearchParams({
    underlying: $("und").value, otm: $("otm").value,
    timeframe_minutes: $("otf").value, reference: $("ref").value, adx_min: $("amin").value,
    candle_type: $("optCandle").value,
  });
  if ($("exp").value) q.set("expiry", $("exp").value);
  $("btnScan").disabled = true;
  $("chain").innerHTML = '<tr><td colspan="14" class="mut">Scanning…</td></tr>';
  try {
    const d = await api("/api/options/chain?" + q.toString());
    $("chainMeta").textContent =
      d.underlying + " " + d.expiry + " · " + d.reference + " " + d.reference_symbol + " " + n(d.spot) +
      " · ATM " + d.atm_strike + " · step " + d.strike_step + " · " + tfCode(d.timeframe_minutes) +
      " · " + (d.candle_type === "heikin_ashi" ? "Heikin Ashi" : "Normal candle") + " · ADX>" +
      n(d.adx_min,0) + " · " + d.above_vwap.length + " above Advanced VWAP · " + d.entry_ready.length + " entry-ready" +
      (d.missing_legs && d.missing_legs.length ? " · not listed: " + d.missing_legs.join(", ") : "");
    renderChain(d);
  } catch (e) {
    note(e.message);
    $("chain").innerHTML = '<tr><td colspan="14" class="down"></td></tr>';
    $("chain").querySelector("td").textContent = e.message;
  } finally { $("btnScan").disabled = false; }
}

function renderChain(d) {
  const rows = d.rows || [];
  const tb = $("chain");
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="14" class="mut">No rows.</td></tr>'; return; }
  tb.innerHTML = rows.map((r) => {
    const why = r.error ? r.error
      : (r.reasons || []).filter((x) => !x.startsWith("all entry")).join("; ");
    const stc = r.supertrend_direction === -1 ? "up" : "down";
    return `<tr class="${r.entry_ready ? "ready" : ""}">
      <td class="l">${esc(r.display_name || r.symbol)}</td>
      <td class="l">${esc(r.option_type || "")}</td><td>${n(r.strike,0)}</td>
      <td>${n(r.ltp)}</td><td>${n(r.vwap)}</td>
      <td class="${r.price_above_vwap ? "yes" : "mut"}">${r.price_above_vwap ? "yes" : "no"}</td>
      <td>${n(r.rsi)}</td><td>${n(r.rsi_ema_21)}</td><td>${n(r.price_ema_21)}</td>
      <td class="${stc}">${n(r.supertrend)}</td><td>${n(r.adx)}</td>
      <td class="${r.entry_ready ? "yes" : "mut"}">${r.entry_ready ? "READY" : "no"}</td>
      <td class="l mut" title="${esc(why)}">${esc(why.slice(0,52))}</td>
      <td style="white-space:nowrap">
        <button type="button" class="sm chartOpt" data-strike="${r.strike}"
          data-opt="${esc(r.option_type)}"
          title="Open this contract and the underlying future side by side">Chart</button>
        <button type="button" class="sm watchOpt" data-sid="${esc(r.security_id)}"
          data-strike="${r.strike}" data-opt="${esc(r.option_type)}"
          data-lot="${r.lot_size}" title="Watch and wait for the signal">Watch</button>
        <button type="button" class="sm go buyOpt" data-sid="${esc(r.security_id)}"
          data-strike="${r.strike}" data-opt="${esc(r.option_type)}"
          data-lot="${r.lot_size}" data-ltp="${r.ltp == null ? "" : r.ltp}"
          title="Buy now, skipping the signal: market or limit">Buy</button>
      </td>
    </tr>`;
  }).join("");

  // Chart: the contract plus its underlying future, so the option and what drives
  // it are visible together.
  tb.querySelectorAll(".chartOpt").forEach((btn) => {
    btn.onclick = () => {
      const und = $("und").value;
      const leg = `opt:${und}:${d.expiry}:${Number(btn.dataset.strike)}:${btn.dataset.opt}`;
      openCharts([leg, `fut:${und}`], tfCode($("otf").value));
    };
  });

  tb.querySelectorAll(".buyOpt").forEach((btn) => {
    btn.onclick = async () => {
      const lots = Number($("lots").value) || 1;
      const qty = lots * Number(btn.dataset.lot);
      const ltp = btn.dataset.ltp === "" ? null : Number(btn.dataset.ltp);
      const choice = await orderDialog({
        title: `BUY ${qty} (${lots} lot${lots > 1 ? "s" : ""}) × ${$("und").value} ` +
          `${Number(btn.dataset.strike)} ${btn.dataset.opt}`,
        sub: `LTP ${n(ltp)} · skips the signal · ${RISK.stop_loss_pct || 3}% protective stop`,
        side: "BUY", ltp, tick: 0.05,
        product: RISK.default_product, exitMode: RISK.exit_mode,
      });
      if (!choice) return;
      btn.disabled = true;
      try {
        const r = await api("/api/options/buy", { method:"POST", body: JSON.stringify({
          security_id: btn.dataset.sid, underlying: $("und").value, expiry: d.expiry,
          strike: Number(btn.dataset.strike), option_type: btn.dataset.opt, lots,
          timeframe_minutes: Number($("otf").value), adx_min: Number($("amin").value),
          candle_type: d.candle_type,
          confirm: true, ...choice,
        }) });
        const p = r.watch && r.watch.position;
        note((p ? `Bought at ${n(p.entry_price)}` + (p.exit_mode === "strategy" ? " — no stop"
                   : ` — stop at ${n(p.stop_price)}`)
                : `Limit buy working at ${n(choice.limit_price)}`) + ". See the Trade tab.", "ok");
      } catch (e) { note(e.message); }
      btn.disabled = false;
    };
  });

  tb.querySelectorAll(".watchOpt").forEach((btn) => {
    btn.onclick = async () => {
      const lots = Number($("lots").value) || 1;
      if (!confirm("Watch this contract?\n\n" + lots + " lot(s) = " + (lots * Number(btn.dataset.lot)) +
          " qty.\nThe engine will ask for approval before buying.")) return;
      try {
        await api("/api/options/watches", { method:"POST", body: JSON.stringify({
          security_id: btn.dataset.sid, underlying: $("und").value,
          expiry: d.expiry, strike: Number(btn.dataset.strike),
          option_type: btn.dataset.opt, lots,
          timeframe_minutes: Number($("otf").value), adx_min: Number($("amin").value),
          candle_type: d.candle_type,
        }) });
        note("Option watch added — see the Trade tab.", "ok");
      } catch (e) { note(e.message); }
    };
  });
}

/* ---------------------------------------------------------------- baskets */
const BK_KNOWN = new Map();   // suggestion label -> symbol id
let BK_TIMER = null;

function addLegRow() {
  const tb = $("bkLegRows");
  if (tb.children.length >= 10) { note("A basket is limited to 10 legs."); return; }
  const i = tb.children.length + 1;
  tb.insertAdjacentHTML("beforeend", `<tr>
    <td class="l"><input class="bksym" list="bkSymList" autocomplete="off" spellcheck="false"
        aria-label="Symbol for leg ${i}" placeholder="SBIN, NIFTY 25000 CE, BANKNIFTY FUT…" /></td>
    <td class="l"><select class="bkside" aria-label="Side for leg ${i}">
        <option value="LONG">BUY</option><option value="SHORT">SELL</option></select></td>
    <td><input class="bklots" type="number" min="1" step="1" value="1" aria-label="Lots for leg ${i}" /></td>
    <td class="l mut bkres">—</td>
    <td><button type="button" class="sm bkrm" aria-label="Remove leg ${i}">✕</button></td>
  </tr>`);
  const row = tb.lastElementChild;
  const sym = row.querySelector(".bksym");
  sym.addEventListener("input", () => {
    clearTimeout(BK_TIMER);
    BK_TIMER = setTimeout(() => suggestSymbols(sym.value), 200);
    showResolved(row);
  });
  sym.addEventListener("change", () => showResolved(row));
  row.querySelector(".bkrm").onclick = () => { row.remove(); ensureLegRows(); };
}
function ensureLegRows() {
  const tb = $("bkLegRows");
  while (tb.children.length < 2) addLegRow();
}

async function suggestSymbols(text) {
  try {
    const d = await api("/api/charts/symbols?" + new URLSearchParams({ q: text.trim(), limit: "30" }));
    // Index spots cannot be traded and baskets cannot nest, so neither is offered.
    const list = (d.symbols || []).filter((s) => !/^(idx|basket):/.test(s.id));
    for (const s of list) BK_KNOWN.set(s.label, s.id);
    $("bkSymList").innerHTML = list.map((s) =>
      `<option value="${esc(s.label)}">${esc(s.group)}</option>`).join("");
  } catch (e) { /* suggestions are optional */ }
}

function legSymbolId(text) {
  const t = (text || "").trim();
  if (!t) return "";
  if (BK_KNOWN.has(t)) return BK_KNOWN.get(t);
  const m = /^(eq|opt|fut):(.+)$/i.exec(t);
  if (m) return m[1].toLowerCase() + ":" + m[2].toUpperCase();
  // "SBIN — State Bank of India" or a bare ticker: an NSE stock.
  return "eq:NSE:" + t.toUpperCase().split(/[\s—]/)[0];
}
function showResolved(row) {
  row.querySelector(".bkres").textContent = legSymbolId(row.querySelector(".bksym").value) || "—";
}

$("bkAddLeg").onclick = addLegRow;
$("bkCreate").onclick = async () => {
  const legs = [];
  for (const row of $("bkLegRows").children) {
    const symbol = legSymbolId(row.querySelector(".bksym").value);
    if (!symbol) continue;
    legs.push({ symbol, direction: row.querySelector(".bkside").value,
                lots: Math.max(1, Math.floor(Number(row.querySelector(".bklots").value) || 1)) });
  }
  if (!legs.length) { note("Type a symbol for at least one leg."); return; }
  const sl = $("bkSl").value.trim(), tp = $("bkTp").value.trim();
  $("bkCreate").disabled = true;
  try {
    const b = await api("/api/baskets", { method: "POST", body: JSON.stringify({
      name: $("bkName").value.trim() || "basket", legs,
      timeframe_minutes: Number($("bkTf").value),
      stop_loss_pct: sl ? Number(sl) : null, target_pct: tp ? Number(tp) : null,
      product: $("bkProd").value || null, exit_mode: $("bkExit").value || null }) });
    note(`Basket "${b.name}" saved with ${b.leg_count} legs.`, "ok");
    $("bkName").value = "";
    $("bkLegRows").innerHTML = "";
    ensureLegRows();
    loadBaskets();
  } catch (e) { note(e.message); }
  $("bkCreate").disabled = false;
};

const pnlSpan = (v) => v == null ? "—"
  : `<span class="${v > 0 ? "up" : v < 0 ? "down" : "mut"}">${v > 0 ? "+" : ""}${n(v)}</span>`;

function basketCard(b) {
  const pill = { open: "paper", watching: "on" }[b.status] || "";
  const legs = b.legs.map((l) => {
    const w = l.watch || {};
    const p = w.position;
    const side = l.side || sideOf(l.direction);
    const why = w.last_error || w.notes || "";
    return `<tr>
      <td class="l">${esc(l.label || l.symbol)}</td>
      <td class="l ${side === "SELL" ? "down" : "up"}">${side}</td>
      <td>${l.quantity}</td>
      <td class="l">${esc(w.state ? w.state.replace(/_/g, " ") : "not set up")}</td>
      <td>${p ? n(p.entry_price) : "—"}</td><td>${n(l.ltp)}</td>
      <td>${stopCell(p)}</td><td>${p ? pnlSpan(p.unrealised_pnl) : "—"}</td>
      <td class="l mut" title="${esc(why)}">${esc(why.slice(0, 40))}</td>
    </tr>`;
  }).join("");
  return `<div class="bkcard ${b.partial ? "partial" : b.status === "open" ? "open" : ""}">
    <div class="top">
      <h3>${esc(b.name)}</h3>
      <span class="pill ${pill}">${esc(b.status)}</span>
      ${b.partial ? `<span class="pill bad">only ${b.open_legs} of ${b.leg_count} legs open</span>` : ""}
      <span class="nums">Unrealised ${pnlSpan(b.unrealised_pnl)} · Realised ${pnlSpan(b.realised_pnl)}
        · <span title="Sum or difference of the leg prices, as the basket chart draws it">Premium
          ${b.premium_now == null ? "—" : n(b.premium_now) + " pts"}</span>
        <span class="mut" title="Σ ± quantity × price">(₹${b.value_now == null ? "—" : n(b.value_now)})</span></span>
      <span class="mut nums">stop ${b.stop_loss_pct ? b.stop_loss_pct + "%" : "default"} per leg
        · target ${b.target_pct ? b.target_pct + "%" : "none"} · ${esc(tfCode(b.timeframe_minutes))}
        · ${b.product === "DELIVERY" ? "delivery" : "intraday"}${b.exit_mode ? " · " + esc(EXIT_TEXT[b.exit_mode] || b.exit_mode) : ""}</span>
      <div class="grow"></div>
      <button type="button" class="sm" data-bkcombo="${esc(b.id)}"
        title="Spot, combined premium, calls and puts on one 2 × 2 screen">Combo</button>
      <button type="button" class="sm" data-bkchart="${esc(b.id)}"
        title="Combined basket value with indicators, beside each leg">Chart</button>
      <button type="button" class="sm go" data-bkexec="${esc(b.id)}"
        ${["open", "uncertain"].includes(b.status) ? "disabled" : ""}
        title="${b.status === "uncertain" ? "Broker acceptance is indeterminate; reconcile the broker terminal before retrying" : "Execute this basket"}">Execute</button>
      <button type="button" class="sm danger" data-bkexit="${esc(b.id)}"
        ${b.open_legs ? "" : "disabled"}>Exit all</button>
      ${b.status === "watching"
        ? `<button type="button" class="sm" data-bkdisarm="${esc(b.id)}">Stop watching</button>`
        : `<button type="button" class="sm" data-bkarm="${esc(b.id)}" ${["open", "uncertain"].includes(b.status) ? "disabled" : ""}
             title="${b.status === "uncertain" ? "Reconcile indeterminate broker acceptance before arming entries" : "Each leg waits for its own entry signal and asks for approval separately"}">Watch legs</button>`}
      <button type="button" class="sm" data-bkdel="${esc(b.id)}">Delete</button>
    </div>
    <div class="scroll"><table>
      <thead><tr><th class="l">Leg</th><th class="l">Side</th><th>Qty</th><th class="l">State</th>
        <th>Entry</th><th>LTP</th><th>Stop</th><th>P&amp;L</th><th class="l">Note</th></tr></thead>
      <tbody>${legs}</tbody></table></div>
  </div>`;
}

async function loadBaskets() {
  let d;
  try { d = await api("/api/baskets"); } catch (e) { note(e.message); return; }
  const list = d.baskets || [];
  $("bkCount").textContent = list.length ? `(${list.length})` : "";
  const box = $("bkList");
  if (!list.length) { box.innerHTML = '<p class="mut">No baskets yet.</p>'; return; }
  box.innerHTML = list.map(basketCard).join("");
  const find = (id) => list.find((b) => b.id === id);

  box.querySelectorAll("[data-bkcombo]").forEach((btn) => {
    btn.onclick = () => {
      const b = find(btn.dataset.bkcombo);
      if (b) window.open("/combo?" + new URLSearchParams({ basket: b.id, tf: tfCode(b.timeframe_minutes) }),
                         "matheranCombo");
    };
  });
  box.querySelectorAll("[data-bkchart]").forEach((btn) => {
    btn.onclick = () => {
      const b = find(btn.dataset.bkchart);
      if (b) openCharts([b.chart_symbol, ...b.legs.map((l) => l.symbol)].slice(0, 8),
                        tfCode(b.timeframe_minutes));
    };
  });
  box.querySelectorAll("[data-bkexec]").forEach((btn) => {
    btn.onclick = async () => {
      const b = find(btn.dataset.bkexec);
      if (!b) return;
      const legs = b.legs.map((l) => ({
        symbol: l.symbol, label: l.label || l.symbol, side: l.side || sideOf(l.direction),
        quantity: l.quantity, ltp: l.ltp,
      }));
      const choice = await orderDialog({
        title: `Execute "${b.name}"`,
        sub: "Bought legs are sent first. Each leg gets its own protective stop " +
          `(${b.stop_loss_pct ? b.stop_loss_pct + "%" : "default"}).`,
        legs, side: "BUY", product: b.product, exitMode: b.exit_mode || RISK.exit_mode,
        cashShort: legs.some((l) => l.side === "SELL" && l.symbol.startsWith("eq:")),
      });
      if (!choice) return;
      btn.disabled = true;
      try {
        const r = await api(`/api/baskets/${b.id}/execute`, { method: "POST",
          body: JSON.stringify({ confirm: true, ...choice }) });
        const failed = (r.legs || []).filter((x) => x.status !== "sent");
        if (failed.length) {
          note(`${r.partial ? "PARTIAL — " : ""}${r.sent} of ${r.legs.length} legs sent. ` +
            failed.map((x) => `${x.label || x.symbol}: ${x.error}`).join("; "));
        } else {
          note(`"${b.name}" executed: ${r.sent} ${r.order_type === "LIMIT" ? "limit orders working" : "orders sent"} ` +
            `(${r.mode}, ${String(r.product || "").toLowerCase()}).`, "ok");
        }
      } catch (e) { note(e.message); }
      loadBaskets();
    };
  });
  box.querySelectorAll("[data-bkexit]").forEach((btn) => {
    btn.onclick = async () => {
      const b = find(btn.dataset.bkexit);
      if (!b || !confirm(`Exit every open leg of "${b.name}" at market?\n\nSold legs are bought back first.`)) return;
      btn.disabled = true;
      try {
        const r = await api(`/api/baskets/${b.id}/exit`, { method: "POST" });
        const failed = (r.legs || []).filter((x) => x.status === "failed");
        note(failed.length
          ? "Some legs did not exit: " + failed.map((x) => `${x.label || x.symbol}: ${x.error}`).join("; ")
          : "Exit orders sent.", failed.length ? undefined : "ok");
      } catch (e) { note(e.message); }
      loadBaskets();
    };
  });
  box.querySelectorAll("[data-bkarm]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/baskets/${btn.dataset.bkarm}/arm`, { method: "POST" });
        note("Legs are being watched. Each one asks for approval when its own conditions line up.", "ok");
      } catch (e) { note(e.message); }
      loadBaskets();
    };
  });
  box.querySelectorAll("[data-bkdisarm]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/baskets/${btn.dataset.bkdisarm}/disarm`, { method: "POST" });
        note("Stopped watching the legs. Open legs keep their stops and exits.", "ok");
      } catch (e) { note(e.message); }
      loadBaskets();
    };
  });
  box.querySelectorAll("[data-bkdel]").forEach((btn) => {
    btn.onclick = async () => {
      const b = find(btn.dataset.bkdel);
      if (!b || !confirm(`Delete basket "${b.name}"? Its leg watches are removed too.`)) return;
      try {
        await api(`/api/baskets/${b.id}`, { method: "DELETE" });
        note("Basket deleted.", "ok");
      } catch (e) {
        if (/still hold|in flight/.test(e.message) && confirm(e.message +
            "\n\nForget the grouping anyway? The open legs stay protected as ordinary watches.")) {
          try { await api(`/api/baskets/${b.id}?force=true`, { method: "DELETE" }); note("Basket deleted.", "ok"); }
          catch (e2) { note(e2.message); }
        } else { note(e.message); }
      }
      loadBaskets();
    };
  });
}

/* ---------------------------------------------------------------- journal */
async function loadJournal() {
  try {
    const d = await api("/api/trades?limit=200");
    const rows = (d.trades || []).slice().reverse();
    $("pnlSum").textContent = rows.length
      ? "· realised " + (d.realised_pnl >= 0 ? "+" : "") + n(d.realised_pnl) + " · " + d.wins + "W / " + d.losses + "L"
      : "";
    $("trades").innerHTML = rows.length ? rows.map((t) => `<tr>
        <td class="l">${clock(t.exit_time)}</td>
        <td class="l">${esc(instName(t.instrument))}</td>
        ${dirCell(t.direction)}
        <td>${t.quantity}</td><td>${n(t.entry_price)}</td><td>${n(t.exit_price)}</td>
        <td class="${t.pnl >= 0 ? "up" : "down"}">${t.pnl >= 0 ? "+" : ""}${n(t.pnl)}</td>
        <td class="${t.pnl >= 0 ? "up" : "down"}">${n(t.pnl_pct)}</td>
        <td class="l">${esc(reasonText(t.exit_reason, t.direction))}${t.exit_note
          ? `<div class="mut" style="font-size:11.5px;white-space:normal;max-width:440px">${esc(t.exit_note)}</div>`
          : ""}</td>
        <td class="l">${esc(t.mode)}${t.product === "DELIVERY" ? " · delivery" : ""}</td></tr>`).join("")
      : '<tr><td colspan="10" class="mut">No trades yet.</td></tr>';
  } catch (e) {}

  try {
    const p = await api("/api/positions");
    const rows = p.engine_positions || [];
    $("positions").innerHTML = rows.length ? rows.map((x) => `<tr>
        <td class="l">${esc(instName(x.instrument))}</td>
        ${dirCell(x.direction)}
        <td>${x.quantity}</td><td>${n(x.entry_price)}</td><td>${n(x.ltp)}</td>
        <td>${stopCell(x)}</td><td>${x.exit_mode !== "strategy" && x.target_price ? n(x.target_price) : "—"}</td>
        <td class="${x.unrealised_pnl >= 0 ? "up" : "down"}">${n(x.unrealised_pnl)}</td>
        <td><button type="button" class="sm danger" data-pexit="${esc(x.watch_id)}">Exit</button></td>
      </tr>`).join("") : '<tr><td colspan="9" class="mut">Flat.</td></tr>';
    $("positions").querySelectorAll("[data-pexit]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("Exit this position at market?")) return;
        try { await api("/api/watches/" + b.dataset.pexit + "/exit", { method:"POST" }); }
        catch (e) { note(e.message); }
        loadJournal();
      };
    });
  } catch (e) {}
}

/* ---------------------------------------------------------------- scanner */
/* Read-only: the Scanner never places an order or creates a watch. Every string the
   server sends (names, notes, messages, details, labels) goes through esc() or
   textContent. Controls are read by id; none carries data-sec / data-key. */
const SC = {
  loaded: false,        // GET /api/scanner answered at least once
  cat: null,            // scanner catalog (rules catalog + on + timeframes)
  defaults: null,       // { buy_rules }
  config: {},           // saved scanner options (max_requests_per_30min, …)
  buy: [], sell: [],    // the rows on screen
  linked: true,         // SELL mirrors BUY
  buyReset: false,      // BUY rows are the defaults and untouched: Save sends null
  dirty: false,         // edited since the last load or save (survives tab switches)
  unis: [],             // universes info()
  uniSel: new Set(),    // ticked universe ids
  uniLoading: new Set(),
  custom: [],           // "NSE:RELIANCE", "BSE:TCS", "MCX:GOLD"
  canSave: false, mcxCharts: true, dataSource: "",
  scan: null,           // the last status summary seen
  scanId: null,         // the job id SC.results/SC.next belong to (F11)
  next: 0,              // since cursor for /api/scanner/status
  results: [],
  pollTimer: null, pollSeq: 0,
  watchState: new Map(), // scan id + seq + side -> adding/added/duplicate/retry
  ownJobs: new Set(),   // ids of the jobs this page started
  auto: null,           // auto-rescan: { interval, armed, timer, failures }; null = not armed
  lastState: "", lastDecile: -1, renderKey: "", focusCancel: false, estimate: null,
  previewTimer: null, estTimer: null, estSeq: 0, symTimer: null, extraLoaded: false,
  sort: { BUY: { key: "met", dir: -1 }, SELL: { key: "met", dir: -1 } },
};
const SC_ACTIVE = ["loading", "running", "waiting", "cancelling"];
const scActive = () => !!(SC.scan && SC_ACTIVE.includes(SC.scan.state));
const fmtInt = (v) => (v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString("en-IN"));
function fmtDur(s) {
  s = Math.max(0, Math.round(Number(s) || 0));
  if (s < 60) return s + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  return Math.floor(s / 3600) + " h " + Math.round((s % 3600) / 60) + " min";
}
const fmtMS = (s) => { s = Math.max(0, Math.round(Number(s) || 0));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };

const SC_BUY = makeRuleEditor({
  tbody: $("scBuyRows"), addBtn: $("scBuyAdd"), rows: () => SC.buy, catalog: () => SC.cat,
  label: "BUY condition", labelLower: "BUY condition", timeframes: true, reorder: true,
  readOnly: () => false, colspan: 8, paramAttr: "pk",
  emptyHtml: '<tr><td colspan="8" class="l mut">No BUY conditions: add at least one.</td></tr>',
  newRow: (fresh) => ({ tf: "15m", join: "AND", left: fresh("close"), op: "above",
                        right: fresh("vwap"), on: "live", candle_type: "normal" }),
  onChange: (rerender) => { SC.buyReset = false; scChanged(rerender ? "buy" : ""); },
});
const SC_SELL = makeRuleEditor({
  tbody: $("scSellRows"), addBtn: $("scSellAdd"), rows: () => SC.sell, catalog: () => SC.cat,
  label: "SELL condition", labelLower: "SELL condition", timeframes: true, reorder: true,
  readOnly: () => SC.linked, colspan: 8, paramAttr: "pk",
  emptyHtml: '<tr><td colspan="8" class="l mut">No SELL conditions: add at least one.</td></tr>',
  newRow: (fresh) => ({ tf: "15m", join: "AND", left: fresh("close"), op: "below",
                        right: fresh("vwap"), on: "live", candle_type: "normal" }),
  onChange: (rerender) => scChanged(rerender ? "sell" : ""),
});

/* What is on screen: preview, estimate and Run send this (never buy_rules: null). */
function scScreenState() {
  return {
    buy_rules: SC.buy,
    sell_linked: SC.linked,
    sell_rules: SC.linked ? null : SC.sell,
    universes: SC.unis.map((u) => u.id).filter((id) => SC.uniSel.has(id)),
    custom_symbols: SC.custom.slice(),
    side: $("scSide").value,
    evaluation: $("scEval").value,
  };
}

/* Something on screen changed: mark dirty, re-render if asked, refresh the read-back
   and the estimate (debounced). */
function scChanged(rerender) {
  SC.dirty = true;
  if (rerender === "buy") SC_BUY.render();
  if (rerender === "sell") SC_SELL.render();
  $("scSaveState").textContent = "unsaved changes";
  scQueuePreview();
  scQueueEstimate();
}
function scQueuePreview() { clearTimeout(SC.previewTimer); SC.previewTimer = setTimeout(scPreview, 350); }
function scQueueEstimate() { clearTimeout(SC.estTimer); SC.estTimer = setTimeout(scEstimate, 600); }

async function loadScanner() {
  let d;
  try { d = await api("/api/scanner"); }
  catch (e) { $("scTables").innerHTML = '<p class="no2"></p>'; $("scTables").firstChild.textContent = e.message; scAnnounce(e.message); return; }
  SC.cat = d.catalog;
  SC.defaults = d.defaults;
  SC.config = d.config || {};
  SC.canSave = !!d.can_save;
  SC.mcxCharts = d.mcx_charts !== false;
  SC.dataSource = d.data_source || "";
  SC.unis = d.universes || [];
  // Leaving the tab and coming back must not throw away edits in progress.
  if (!SC.dirty) {
    const c = SC.config;
    SC.buy = clone(c.buy_rules || []);
    SC.sell = clone(c.sell_rules || []);
    SC.linked = c.sell_linked !== false;
    SC.buyReset = !c.buy_customised;
    SC.uniSel = new Set(c.universes || []);
    SC.custom = (c.custom_symbols || []).slice();
    $("scSide").value = c.side || "both";
    $("scEval").value = c.evaluation || "auto";
    // Only the select's default: loading never arms auto-rescan.
    $("scAuto").value = String(SC.auto && SC.auto.armed ? SC.auto.interval
                                                        : (c.auto_rescan_minutes || 0));
    $("scSaveState").textContent = c.buy_customised || !c.sell_linked
      ? "saved in config.yaml" : "the default conditions (not yet customised)";
  }
  SC.loaded = true;
  $("scLinked").checked = SC.linked;
  $("scSave").disabled = !SC.canSave;
  $("scSave").title = SC.canSave ? "" : "Settings can only be saved from this machine";
  if (!SC.canSave) $("scSaveState").textContent = "Settings can only be saved from this machine";
  SC_BUY.render();
  SC_SELL.render();
  scAutoUI();
  scRenderUnis();
  scRenderChips();
  scRenderBudget(d.budget);
  scPreview();
  scEstimate();
  // Showing the tab (or a reload) re-reads the current scan from the start (since=0).
  const overviewId = d.scan && d.scan.id ? d.scan.id : null;
  if (overviewId !== SC.scanId) SC.watchState.clear();
  SC.scan = d.scan && d.scan.state ? d.scan : SC.scan;
  SC.scanId = overviewId;
  SC.next = 0;
  SC.results = [];
  scPoll();
}

async function scPreview() {
  if (!SC.loaded) return;
  const box = $("scRuleText");
  try {
    const st = scScreenState();
    const d = await api("/api/scanner/preview", { method: "POST", body: JSON.stringify({
      buy_rules: st.buy_rules, sell_linked: st.sell_linked, sell_rules: st.sell_rules }) });
    if (SC.linked) { SC.sell = clone(d.sell.rules); SC_SELL.render(); }
    const per = d.per_symbol || {};
    box.className = "rulebox";
    box.innerHTML = `<div><strong>BUY when</strong> ${esc(d.buy.text)}</div>
      <div><strong>SELL when</strong> ${esc(d.sell.text)}${d.sell.linked
        ? ' <span class="mut">(the mirror of BUY)</span>' : ""}</div>
      <div class="mut">Data per NSE/BSE symbol: first scan of the day ${esc(per.first_scan_of_day)}
        requests, then ${esc(per.repeat)} per scan (prior sessions are cached for the day).</div>`;
  } catch (e) {
    box.className = "rulebox bad";
    box.textContent = e.message;
  }
}

$("scLinked").onchange = () => {
  if ($("scLinked").checked) {
    if (!confirm("Discard the SELL edits and mirror BUY again?")) { $("scLinked").checked = false; return; }
    SC.linked = true;
  } else {
    // Unlinking starts from the current mirror, now editable.
    SC.linked = false;
  }
  scChanged("sell");
};
$("scReset").onclick = () => {
  if (!SC.defaults) return;
  if (!confirm("Replace the BUY rows with the seven default conditions?")) return;
  SC.buy = clone(SC.defaults.buy_rules);
  scChanged("buy");
  SC.buyReset = true;   // after scChanged: Save sends null until a row is edited
};
$("scSave").onclick = async () => {
  if (!SC.canSave) return;
  const st = scScreenState();
  const body = { scanner: {
    buy_rules: SC.buyReset ? null : st.buy_rules,
    sell_rules: SC.linked ? null : st.sell_rules,
    universes: st.universes, custom_symbols: st.custom_symbols,
    side: st.side, evaluation: st.evaluation,
    auto_rescan_minutes: Number($("scAuto").value) || 0,
  } };
  $("scSave").disabled = true;
  try {
    await api("/api/settings/config", { method: "PUT", body: JSON.stringify(body) });
    note("Scanner settings saved to config.yaml.", "ok");
    SC.dirty = false;
    await loadScanner();
  } catch (e) { note(e.message); }
  $("scSave").disabled = !SC.canSave;
};

/* ---- universes and custom symbols ---- */
function scUniText(u) {
  const unit = u.id === "mcx" ? "commodities" : "stocks";
  let where = "";
  if (u.source === "snapshot") where = "snapshot of " + (u.as_of || "?");
  else if (u.source === "cache") where = "cache of " + (u.as_of || "?");
  else if (u.source === "Upstox instrument master") where = "Upstox master of " + (u.as_of || "?");
  else if (u.source) where = "NSE list of " + (u.as_of || "?");
  const size = u.size != null ? fmtInt(u.size) + " " + unit
    : (SC.uniLoading.has(u.id) ? "loading…" : "size loads when ticked");
  return [u.label, size, where].filter(Boolean).join(" · ");
}
function scRenderUnis() {
  const box = $("scUnis");
  const focused = document.activeElement && box.contains(document.activeElement)
    ? document.activeElement.id : "";
  box.innerHTML = SC.unis.map((u) => `<label class="inline" for="scU-${esc(u.id)}">
      <input type="checkbox" id="scU-${esc(u.id)}" data-sc-uni="${esc(u.id)}"
        ${SC.uniSel.has(u.id) ? "checked" : ""} />
      <span>${esc(scUniText(u))}${u.error ? `<span class="err">${esc(u.error)}</span>` : ""}</span></label>`).join("");
  box.querySelectorAll("[data-sc-uni]").forEach((el) => {
    el.onchange = () => {
      const id = el.dataset.scUni;
      if (el.checked) SC.uniSel.add(id); else SC.uniSel.delete(id);
      const u = SC.unis.find((x) => x.id === id);
      if (el.checked && u && u.size == null && (id === "fno" || id === "mcx")) scLoadUni(id);
      scRenderTotal();
      scChanged("");
    };
  });
  if (focused && $(focused)) $(focused).focus();
  scRenderTotal();
}
async function scLoadUni(id) {
  SC.uniLoading.add(id);
  scRenderUnis();
  $("scTotal").textContent = id === "mcx" ? "loading the MCX list…" : "loading the F&O list…";
  try {
    const d = await api("/api/scanner/universes?" + new URLSearchParams({ load: id }));
    SC.unis = d.universes || SC.unis;
  } catch (e) { note(e.message); }
  SC.uniLoading.delete(id);
  scRenderUnis();
  scQueueEstimate();
}
function scRenderTotal() {
  let total = 0, unknown = [];
  for (const u of SC.unis) {
    if (!SC.uniSel.has(u.id)) continue;
    if (u.size != null) total += Number(u.size) || 0; else unknown.push(u.label);
  }
  total += SC.custom.length;
  const sel = SC.uniSel.size + SC.custom.length;
  $("scTotal").textContent = !sel ? "Nothing selected: tick a universe or add a symbol."
    : `About ${fmtInt(total)} symbols` + (unknown.length ? ` plus ${unknown.join(", ")} (size not loaded yet)` : "") +
      (SC.uniSel.size > 1 || (SC.uniSel.size && SC.custom.length)
        ? ": an upper bound, overlaps are removed when the scan starts." : ".");
}

const SC_SYM_RE = /^[A-Z0-9][A-Z0-9&\-_.]{0,29}$/;
function scParseSymbol(text) {
  const t = String(text || "").trim().toUpperCase();
  const m = /^(NSE|BSE|MCX)\s*:\s*(.+)$/.exec(t);
  // A pasted suggestion label ("RELIANCE — Reliance Industries") counts by its ticker.
  const exch = m ? m[1] : "NSE", sym = (m ? m[2] : t).split(" — ")[0].trim();
  return SC_SYM_RE.test(sym) ? exch + ":" + sym : null;
}
function scRenderChips() {
  const ul = $("scChips");
  ul.innerHTML = SC.custom.map((s, i) => `<li><span>${esc(s)}</span>
      <button type="button" class="sm" data-sc-chip="${i}" aria-label="Remove ${esc(s)}">✕</button></li>`).join("");
  ul.querySelectorAll("[data-sc-chip]").forEach((b) => {
    b.onclick = () => {
      const i = Number(b.dataset.scChip);
      SC.custom.splice(i, 1);
      scRenderChips(); scRenderTotal(); scChanged("");
      const next = ul.querySelector(`[data-sc-chip="${Math.min(i, SC.custom.length - 1)}"]`);
      (next || $("scSym")).focus();
    };
  });
}
function scAddSymbol() {
  const raw = $("scSym").value;
  if (!raw.trim()) return;
  const sym = scParseSymbol(raw);
  if (!sym) { note(`"${raw.trim()}": use SYMBOL, NSE:SYMBOL, BSE:SYMBOL or MCX:COMMODITY`); return; }
  if (SC.custom.includes(sym)) { $("scSym").value = ""; return; }
  if (SC.custom.length >= 200) { note("At most 200 custom symbols."); return; }
  SC.custom.push(sym);
  $("scSym").value = "";
  scRenderChips(); scRenderTotal(); scChanged("");
}
$("scSymAdd").onclick = scAddSymbol;
$("scSym").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") { ev.preventDefault(); scAddSymbol(); }
});
$("scSym").addEventListener("input", () => {
  clearTimeout(SC.symTimer);
  SC.symTimer = setTimeout(() => scSuggest($("scSym").value), 200);
});
async function scSuggest(text) {
  const m = /^\s*(NSE|BSE|MCX)\s*:\s*(.*)$/i.exec(text || "");
  const q = (m ? m[2] : text || "").trim();
  const exchanges = m ? m[1].toUpperCase() : "NSE,BSE,MCX";
  if (!q) return;
  const hint = $("scSymHint");
  const extra = exchanges !== "NSE" && !SC.extraLoaded;
  if (extra) hint.textContent = "loading BSE and MCX symbol lists…";
  try {
    const d = await api("/api/charts/symbols?" + new URLSearchParams({ q, exchanges, limit: "30" }));
    if (exchanges !== "NSE") SC.extraLoaded = true;
    const opts = [];
    for (const s of d.symbols || []) {
      const id = String(s.id || "");
      let mm;
      if ((mm = /^eq:(NSE|BSE):(.+)$/.exec(id))) opts.push([mm[1] + ":" + mm[2], s.label]);
      else if ((mm = /^mcx:([^:]+)/.exec(id))) opts.push(["MCX:" + mm[1], s.label]);
    }
    $("scSymList").innerHTML = opts.map(([v, l]) =>
      `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  } catch (e) { /* suggestions are optional */ }
  if (extra) hint.textContent = "e.g. RELIANCE, BSE:TCS, MCX:GOLD";
}

["scSide", "scEval"].forEach((id) => { $(id).onchange = () => scChanged(""); });
// Auto-rescan: choosing a value never arms it (Run does); Off disarms at once.
$("scAuto").onchange = () => {
  SC.dirty = true;
  $("scSaveState").textContent = "unsaved changes";
  scAutoChanged();
};

/* ---- estimate ---- */
async function scEstimate() {
  if (!SC.loaded) return;
  const mine = ++SC.estSeq;
  const st = scScreenState();
  const box = $("scEst");
  box.className = "sub";
  if (!st.universes.length && !st.custom_symbols.length) {
    box.textContent = "Select at least one universe or custom symbol.";
    return;
  }
  box.textContent = "Estimating the request cost…";
  try {
    const e = await api("/api/scanner/estimate", { method: "POST", body: JSON.stringify(st) });
    if (mine !== SC.estSeq) return;
    SC.estimate = e;
    box.textContent = scEstimateText(e);
  } catch (err) {
    if (mine !== SC.estSeq) return;
    box.className = "sub no2";
    box.textContent = err.message;
  }
}
function scEstimateText(e) {
  const r = e.requests || {}, eta = e.eta_seconds || {};
  const rate = Number(e.rate_per_second) || 6;
  const cap = Number(SC.config.max_requests_per_30min) || 1500;
  // "under the N cap" only when the 30-minute cap, not the pace, sets the time.
  const capped = (reqs, secs) => (Number(secs) > Number(reqs) / rate + 1 ? ` under the ${fmtInt(cap)} cap` : "");
  if (!e.symbols) return "Nothing to scan. " + (e.warnings || []).join(" ");
  let s = `${fmtInt(e.symbols)} symbols` +
    ((e.skipped || []).length ? ` (${fmtInt(e.skipped.length)} skipped)` : "") + ": ";
  if (e.evaluation === "lazy") {
    s += `≈ ${fmtInt(r.lazy_typical)} Upstox requests lazy (about ${fmtDur(eta.min)}` +
      `${capped(r.lazy_typical, eta.min)}); every condition would need ≈ ${fmtInt(r.complete)}` +
      ` and ≈ ${fmtDur(eta.max)}${capped(r.complete, eta.max)}.`;
  } else {
    s += `≈ ${fmtInt(r.complete)} Upstox requests, every condition (about ${fmtDur(eta.max)}` +
      `${capped(r.complete, eta.max)}).`;
  }
  if (Number(r.quotes_per_30s) > 0) s += " + about 1 quote request per 400 symbols every 30 s.";
  s += ` Repeat scans ≈ ${fmtInt(r.repeat)}. ${fmtInt(e.available)} available now.`;
  if ((e.warnings || []).length) s += " " + e.warnings.join(" ");
  return s;
}

/* ---- run, cancel, polling ---- */
function scAnnounce(text) { $("scSr").textContent = text; }
function scRequests(s) {
  const q = s.requests || {};
  return (Number(q.upstox) || 0) + (Number(q.dhan) || 0) + (Number(q.other) || 0);
}
/* trigger "auto" (with interval_minutes) is for the auto-rescan code; Run sends manual. */
async function scRun(trigger, interval) {
  const body = { ...scScreenState(), trigger: trigger === "auto" ? "auto" : "manual" };
  if (body.trigger === "auto") body.interval_minutes = interval;
  $("scRun").disabled = true;
  try {
    const r = await api("/api/scanner/run", { method: "POST", body: JSON.stringify(body) });
    const s = r.scan || {};
    SC.ownJobs.add(s.id);
    // A new job: its results start at seq 1 (F11).
    SC.watchState.clear();
    SC.scanId = s.id; SC.next = 0; SC.results = []; SC.scan = s;
    SC.lastState = s.state; SC.lastDecile = -1; SC.renderKey = "";
    scAnnounce("Scan started.");
    scRenderAll();
    if (body.trigger === "manual") {   // an auto run never moves the focus
      SC.focusCancel = true;
      $("scCancel").focus();
    }
    scPoll();
    return r;
  } catch (e) {
    $("scProgText").textContent = e.message;
    note(e.message);
    scRenderRun();
    throw e;
  }
}
$("scRun").onclick = async () => {
  const minutes = Number($("scAuto").value) || 0;
  if (minutes) {
    $("scRun").disabled = true;
    const refusal = await scAutoRefusal(minutes);
    if (refusal) { $("scAuto").value = "0"; scDisarm(refusal); note(refusal); }
    else scArm(minutes);
  } else scDisarm();
  // The manual run goes ahead either way; nothing chains from a run that was refused.
  scRun("manual").catch(() => scDisarm());
};
$("scCancel").onclick = async () => {
  scDisarm();
  try {
    const r = await api("/api/scanner/cancel", { method: "POST" });
    if (r.scan && r.scan.id === SC.scanId) SC.scan = r.scan;
    scRenderRun();
    scPoll();
  } catch (e) { note(e.message); }
};

function scSchedule(ms) { clearTimeout(SC.pollTimer); SC.pollTimer = setTimeout(scPoll, ms); }
/* One rule: every 1 s while the tab is shown and a scan is active; every 5 s while
   hidden only if auto-rescan is armed; otherwise paused until the tab is shown again,
   which reloads with since=0. */
async function scPoll() {
  clearTimeout(SC.pollTimer);
  SC.pollTimer = null;
  const mine = ++SC.pollSeq;
  const since = SC.next;
  let d;
  try { d = await api("/api/scanner/status?" + new URLSearchParams({ since: String(since) })); }
  catch (e) {
    if (mine !== SC.pollSeq) return;
    $("scProgText").textContent = "Status unavailable: " + e.message;
    if (scActive() && TAB === "scanner") scSchedule(3000);
    return;
  }
  if (mine !== SC.pollSeq) return;
  const s = d.scan || { state: "idle" };
  if (s.id && s.id !== SC.scanId) {
    // A different job than the one held (a new run here or elsewhere): reset the cursor and action state.
    SC.watchState.clear();
    SC.scanId = s.id; SC.next = 0; SC.results = []; SC.lastDecile = -1; SC.renderKey = "";
    if (since > 0) { scPoll(); return; }
  }
  if (s.id) {
    const have = SC.results.length ? SC.results[SC.results.length - 1].seq : 0;
    for (const r of d.results || []) if (r.seq > have) SC.results.push(r);
    SC.next = Math.max(SC.next, Number(d.next) || 0);
  }
  const was = SC.lastState;
  SC.scan = s;
  SC.lastState = s.state;
  scProgressAnnounce(s, was);
  if (TAB === "scanner") scRenderAll();
  if (SC_ACTIVE.includes(s.state)) {
    if (TAB === "scanner") scSchedule(1000);
    else if (SC.auto && SC.auto.armed) scSchedule(5000);
  } else if (SC_ACTIVE.includes(was)) {
    scFinished(s);
  }
}
function scProgressAnnounce(s, was) {
  if (s.state === "waiting" && was !== "waiting") {
    scAnnounce(s.waiting_until ? "Waiting for the Upstox request budget until " + clock(s.waiting_until)
                               : "Waiting for requests in flight");
    return;
  }
  if (s.state === "running" && s.total) {
    const dec = Math.floor((s.scanned / s.total) * 10);
    if (dec > SC.lastDecile && dec > 0 && dec < 10) {
      scAnnounce(`${dec * 10}% scanned (${s.scanned} of ${s.total})`);
    }
    SC.lastDecile = Math.max(SC.lastDecile, dec);
  }
}
/* A scan this page saw running has ended. (Auto-rescan scheduling hooks in here.) */
function scFinished(s) {
  const m = s.matches || {};
  const parts = (s.sides || []).map((side) => `${m[side] || 0} ${side}`);
  if (s.state === "done") {
    scAnnounce(`Scan finished: ${parts.join(", ")} matches of ${s.scanned}`);
  } else {
    scAnnounce(`Scan ${s.state}` + (s.message ? ": " + s.message : "") + ` (${s.scanned} of ${s.total} scanned)`);
  }
  if (SC.focusCancel) {
    SC.focusCancel = false;
    const a = document.activeElement;
    if (TAB === "scanner" && (!a || a === document.body || a === $("scCancel"))) $("scRun").focus();
  }
  scAutoFinished(s);
  scRefreshBudget();
}

/* ---- auto-rescan (one rule): loading never arms it; Run arms it after the budget
   check; only this page's own jobs schedule the next run. ---- */
async function scAutoRefusal(minutes) {
  if (!SC.estimate) await scEstimate();
  const e = SC.estimate;
  if (!e || !e.requests) return "";   // no estimate to check: the server's own check decides
  const cap = Number(SC.config.max_requests_per_30min) || 1500;
  const per30 = (Number(e.requests.repeat) || 0) * 30 / minutes;
  if (per30 <= cap) return "";
  return `Auto-rescan off: every ${minutes} min over ${fmtInt(e.symbols)} symbols needs ≈${fmtInt(Math.round(per30))}` +
    ` requests per 30 min; the scanner may use ${fmtInt(cap)}.`;
}
function scArm(minutes) {
  if (SC.auto) clearTimeout(SC.auto.timer);   // the end of this Run's job schedules the next
  SC.auto = { interval: minutes, armed: true, timer: null, failures: 0 };
  scAutoUI();
}
function scDisarm(reason) {
  if (SC.auto) clearTimeout(SC.auto.timer);
  const was = !!(SC.auto && SC.auto.armed);
  SC.auto = null;
  scAutoUI(reason);
  if (was) scAnnounce("Auto-rescan off" + (reason ? ": " + reason : ""));
}
function scAutoUI(reason) {
  const tab = $("tab-scanner"), hint = $("scAutoHint");
  const armed = !!(SC.auto && SC.auto.armed);
  tab.textContent = armed ? "Scanner · auto" : "Scanner";
  if (armed) tab.setAttribute("aria-label", `Scanner, auto-rescan every ${SC.auto.interval} minutes`);
  else tab.removeAttribute("aria-label");
  const minutes = Number($("scAuto").value) || 0;
  let text = "";
  if (reason) text = reason;
  else if (armed) text = `On: the next scan starts ${SC.auto.interval} min after this one ends.`;
  else if (minutes) text = "starts after the next Run";
  hint.textContent = text;
  hint.hidden = !text;
}
async function scAutoChanged() {
  const minutes = Number($("scAuto").value) || 0;
  if (!minutes) { scDisarm(); return; }
  if (!(SC.auto && SC.auto.armed)) { scAutoUI(); return; }
  const refusal = await scAutoRefusal(minutes);
  if (!(SC.auto && SC.auto.armed)) return;
  if (refusal) { $("scAuto").value = "0"; scDisarm(refusal); note(refusal); return; }
  SC.auto.interval = minutes;   // applies from the next scheduling
  scAutoUI();
}
function scAutoSchedule() {
  if (!(SC.auto && SC.auto.armed)) return;
  clearTimeout(SC.auto.timer);
  SC.auto.timer = setTimeout(scAutoFire, SC.auto.interval * 60000);
}
function scAutoFinished(s) {
  if (!(SC.auto && SC.auto.armed) || !SC.ownJobs.has(s.id)) return;
  if (s.state === "cancelled") scDisarm();
  else if (["done", "stopped", "failed"].includes(s.state)) scAutoSchedule();
}
async function scAutoFire() {
  const a = SC.auto;
  if (!(a && a.armed)) return;
  a.timer = null;
  try {
    await scRun("auto", a.interval);
    a.failures = 0;
  } catch (e) {
    if (SC.auto !== a || !a.armed) return;
    const st = e.status;
    if (st === 429 || st === 409) {            // skipped: stays armed, tries again later
      a.failures = 0;
      if (st === 409) note("skipped: a scan is running");
      scAutoSchedule();
    } else if (!st) {                          // network error: retry, 3 in a row disarm
      a.failures += 1;
      if (a.failures >= 3) scDisarm("Auto-rescan off after 3 failed attempts: " + e.message);
      else scAutoSchedule();
    } else {                                   // 400, 401, 502, …: show it and disarm
      const v = $("scAuto").value;
      scDisarm();
      $("scAuto").value = v;                   // the select keeps its value
      scAutoUI();
      note(e.message);
    }
  }
}
window.addEventListener("pagehide", () => scDisarm());
async function scRefreshBudget() {
  try { scRenderBudget((await api("/api/scanner")).budget); } catch (e) { /* optional */ }
}

/* ---- rendering ---- */
function scRenderBudget(b) {
  if (!b) return;
  const caps = b.caps || {};
  $("scBudget").textContent = `Upstox: ${fmtInt(b.used_total_30m)} of 2,000 requests used in the ` +
    `last 30 min (scanner ${fmtInt(b.used_scanner_30m)} of ${fmtInt(caps.scanner_30m)})`;
}
function scProgText(s) {
  const m = s.matches || {};
  const counts = `${fmtInt(s.scanned)} / ${fmtInt(s.total)} scanned` +
    (s.sides || []).map((side) => ` · ${side} ${m[side] || 0}`).join("") +
    ` · ${fmtInt(scRequests(s))} requests`;
  switch (s.state) {
    case "idle": return s.other ? String(s.other.message || "") : "No scan yet.";
    case "loading": return "Loading the symbol lists…";
    case "waiting":
      return s.waiting_until ? `Waiting for the Upstox request budget until ${clock(s.waiting_until)} · ${counts}`
                             : `Waiting for requests in flight · ${counts}`;
    case "running": return counts + (s.eta_seconds != null ? ` · ETA ${fmtMS(s.eta_seconds)}` : "");
    case "cancelling": return "Cancelling… · " + counts;
    case "done": return "Done · " + counts;
    default:
      return `${s.state.charAt(0).toUpperCase()}${s.state.slice(1)}${s.message ? ": " + s.message : ""} · ${counts}`;
  }
}
function scRenderRun() {
  const s = SC.scan || { state: "idle" };
  const active = scActive();
  $("scRun").disabled = active;
  $("scCancel").disabled = !active || s.state === "cancelling";
  const prog = $("scProg");
  if (active && (s.state === "loading" || !s.total)) prog.removeAttribute("value");
  else {
    prog.max = Math.max(1, Number(s.total) || 1);
    prog.value = s.total ? Number(s.scanned) || 0 : (s.state === "idle" ? 0 : prog.max);
  }
  $("scProgText").textContent = scProgText(s);
  if (s.budget) scRenderBudget(s.budget);
}
function scRenderAll() { scRenderRun(); scRenderResults(); }

const SC_ICON = { true: ["✓", "met", "yes"], false: ["✗", "not met", "no2"],
                  unavailable: ["n/a", "n/a", "mut"], skipped: ["·", "not checked", "mut"] };
function scCondCell(c, col) {
  const [ic, word, cls] = SC_ICON[c.state] || SC_ICON.unavailable;
  // "Price > ST(21, 0.618)": the price is in the LTP column, so show the indicator's value.
  const priceLeft = col && /^\S+ (Price|Close|Open|High|Low) /.test(col.label || "") && c.right != null;
  const v = priceLeft ? c.right : c.left;
  const val = (c.state === "true" || c.state === "false") && v != null ? " " + n(v) : "";
  const tip = [c.detail, c.bars ? c.bars + " bars" : "", c.short_history ? "short history" : ""]
    .filter(Boolean).join(" · ");
  return `<td class="${cls}" title="${esc(tip)}"><span aria-hidden="true">${ic}</span><span class="sr">${word}</span>${esc(val)}</td>`;
}
function scSortValue(r, side, key) {
  if (key === "symbol") return String(r.symbol || "");
  if (key === "ltp") return r.ltp;
  if (key === "chg") return r.change_pct;
  const sr = (r.sides || {})[side];
  return sr ? sr.met : null;
}
function scSorted(rows, side) {
  const st = SC.sort[side] || { key: "met", dir: -1 };
  return rows.slice().sort((a, b) => {
    const va = scSortValue(a, side, st.key), vb = scSortValue(b, side, st.key);
    let c = 0;
    if (va == null && vb != null) return 1;
    if (vb == null && va != null) return -1;
    if (va != null && vb != null) c = (typeof va === "string" ? va.localeCompare(vb) : va - vb) * st.dir;
    return c || String(a.symbol || "").localeCompare(String(b.symbol || ""));
  });
}
function scShortestTf() {
  const s = SC.scan || {};
  let best = null;
  for (const cols of Object.values(s.columns || {})) {
    for (const c of cols) {
      const t = TFS.find((x) => x.id === c.tf);
      if (t && t.minutes < 1440 && (!best || t.minutes < best.minutes)) best = t;
    }
  }
  return best ? best.id : "5m";
}
function scWatchKey(scanId, seq, side) {
  return `${scanId || ""}:${seq}:${side}`;
}
const scWatchUnavailable = (r) => SC.dataSource === "upstox" && r.exchange === "BSE";
function scActions(r, side) {
  const label = esc(r.exchange) + ":" + esc(r.symbol);
  const out = [];
  if (r.chartable && r.chart && (r.exchange !== "MCX" || SC.mcxCharts)) {
    out.push(`<button type="button" class="sm" data-sc-chart="${esc(r.chart)}"
      data-sc-f="chart:${side}:${esc(r.seq)}" aria-label="Chart ${label}">Chart</button>`);
  }
  if (r.tradable && (r.exchange === "NSE" || r.exchange === "BSE")) {
    const key = scWatchKey(SC.scanId, r.seq, side);
    const state = SC.watchState.get(key) || { state: "idle", error: "" };
    const labels = { idle: "Add to watchlist", adding: "Adding…", added: "Added",
                    duplicate: "Already watched", retry: "Retry" };
    const unavailable = scWatchUnavailable(r);
    const text = unavailable ? "BSE watch unavailable" : (labels[state.state] || labels.idle);
    const locked = unavailable || state.state === "adding" || state.state === "added" || state.state === "duplicate";
    const explanation = unavailable
      ? "BSE watch candles are unavailable when Upstox is the active data source; charting remains available."
      : state.state === "retry" && state.error
        ? state.error
        : side === "SELL"
          ? "Create a normal one-share SHORT intraday watch. No order is placed; watch defaults apply."
          : "Create a normal one-share LONG watch. No order is placed; watch defaults apply.";
    out.push(`<button type="button" class="sm${state.state === "added" ? " go" : ""}"
      data-sc-watch="${esc(r.seq)}" data-sc-side="${side}" data-sc-job="${esc(SC.scanId || "")}"
      data-sc-f="watch:${side}:${esc(r.seq)}" aria-label="${esc(text)} ${label}"
      title="${esc(explanation)}" ${locked ? "disabled" : ""}>${esc(text)}</button>`);
  }
  return out.length ? out.join(" ")
    : `<span aria-hidden="true" title="No action is available for this row">—</span><span class="sr">no action</span>`;
}
function scTable(side, s, filter, minMet) {
  const cols = (s.columns || {})[side] || [];
  const rows = SC.results.filter((r) => {
    const sr = (r.sides || {})[side];
    if (filter === "all") return true;
    if (!sr) return false;
    return filter === "match" ? sr.signal : sr.met >= minMet;
  });
  const sorted = scSorted(rows, side);
  const shown = sorted.slice(0, 1000);
  const st = SC.sort[side];
  const sortTh = (key, text, cls) => {
    const on = st.key === key;
    return `<th scope="col" class="${cls || ""}" aria-sort="${on ? (st.dir > 0 ? "ascending" : "descending") : "none"}">
      <button type="button" class="sortb" data-sc-sort="${side}:${key}" data-sc-f="sort:${side}:${key}">${text}${on ? (st.dir > 0 ? " ▲" : " ▼") : ""}</button></th>`;
  };
  const matches = (s.matches || {})[side] || 0;
  const head = sortTh("symbol", "Symbol", "l") + '<th scope="col" class="l">Exch</th>' +
    sortTh("ltp", "LTP") + sortTh("chg", "Chg %") +
    cols.map((c) => `<th scope="col" title="${esc(c.text)}">${esc(c.label)}</th>`).join("") +
    sortTh("met", "Met") + '<th scope="col">Signal</th><th scope="col" class="l">Actions</th>';
  const body = shown.map((r) => {
    const sr = (r.sides || {})[side];
    const tip = [r.name, ...(r.notes || [])].filter(Boolean).join(" · ");
    const chg = r.change_pct == null ? "—"
      : `<span class="${r.change_pct > 0 ? "up" : r.change_pct < 0 ? "down" : "mut"}">${r.change_pct > 0 ? "+" : ""}${n(r.change_pct)}</span>`;
    const conds = sr ? sr.rows.map((cell, i) => scCondCell(cell, cols[i])).join("")
      : `<td class="l no2" colspan="${Math.max(1, cols.length)}" title="${esc(r.error)}">${esc(r.error ? "error: " + String(r.error).slice(0, 90) : r.status)}</td>`;
    const notChecked = sr ? sr.total - sr.checked : 0;
    const met = sr ? `${esc(sr.met)}/${esc(sr.total)}${notChecked > 0 ? ` <span class="mut">(${notChecked} not checked)</span>` : ""}` : "—";
    const signal = sr && sr.signal ? `<span class="yes">${side}</span>` : '<span class="mut">no</span>';
    return `<tr class="${sr && sr.signal ? "ready" : ""}">
      <th scope="row" class="l" title="${esc(tip)}">${esc(r.symbol)}</th>
      <td class="l">${esc(r.exchange)}</td><td>${n(r.ltp)}</td><td>${chg}</td>${conds}
      <td>${met}</td><td>${signal}</td><td class="l">${scActions(r, side)}</td></tr>`;
  }).join("");
  const colspan = 7 + cols.length;
  const more = sorted.length > shown.length
    ? `<tr><td colspan="${colspan}" class="l mut">Showing the first 1,000 of ${fmtInt(sorted.length)} rows.</td></tr>` : "";
  return `<div class="scroll"><table class="scres">
    <caption>${side}: ${fmtInt(matches)} matches of ${fmtInt(s.scanned)} scanned</caption>
    <thead><tr>${head}</tr></thead>
    <tbody>${body || `<tr><td colspan="${colspan}" class="l mut">${s.scanned ? "No rows match this filter." : "No results yet."}</td></tr>`}${more}</tbody>
  </table></div>`;
}
function scRenderResults() {
  const s = SC.scan;
  const box = $("scTables");
  if (!s || !s.id) {
    box.innerHTML = '<p class="mut">Run a scan to see results.</p>';
    $("scFooter").textContent = "";
    $("scNotes").innerHTML = "";
    SC.renderKey = "";
    return;
  }
  const filter = $("scFilter").value, minMet = Number($("scMinMet").value) || 0;
  const key = [s.id, s.state, SC.results.length, filter, minMet, SC.mcxCharts, SC.dataSource,
               JSON.stringify(SC.sort)].join("|");
  if (key !== SC.renderKey) {
    SC.renderKey = key;
    const focused = document.activeElement && box.contains(document.activeElement)
      ? document.activeElement.dataset.scF : "";
    box.innerHTML = (s.sides || []).filter((x) => x === "BUY" || x === "SELL")
      .map((side) => scTable(side, s, filter, minMet)).join("")
      || '<p class="mut">No side selected.</p>';
    box.querySelectorAll("[data-sc-sort]").forEach((b) => {
      b.onclick = () => {
        const [side, k] = b.dataset.scSort.split(":");
        const st = SC.sort[side];
        if (st.key === k) st.dir = -st.dir; else { st.key = k; st.dir = k === "symbol" ? 1 : -1; }
        scRenderResults();
      };
    });
    box.querySelectorAll("[data-sc-chart]").forEach((b) => {
      b.onclick = () => openCharts([b.dataset.scChart], scShortestTf());
    });
    box.querySelectorAll("[data-sc-watch]").forEach((b) => {
      b.onclick = async () => {
        const scanId = b.dataset.scJob;
        const side = b.dataset.scSide;
        if (!scanId || scanId !== SC.scanId) return;
        const r = SC.results.find((x) => String(x.seq) === b.dataset.scWatch);
        if (!r || !r.tradable || !["NSE", "BSE"].includes(r.exchange) || scWatchUnavailable(r)) return;
        const key = scWatchKey(scanId, r.seq, side);
        SC.watchState.set(key, { state: "adding", error: "" });
        SC.renderKey = "";
        scRenderResults();
        let refreshWatches = false;
        try {
          const body = {
            symbol: r.symbol,
            exchange: r.exchange,
            direction: side === "SELL" ? "SHORT" : "LONG",
            quantity: 1,
          };
          if (side === "SELL") body.product = "INTRADAY";
          await api("/api/watches", { method: "POST", body: JSON.stringify(body) });
          SC.watchState.set(key, { state: "added", error: "" });
          refreshWatches = true;
        } catch (e) {
          if (/\bis already being watched \(watch\b/i.test(e.message)) {
            SC.watchState.set(key, { state: "duplicate", error: e.message });
            refreshWatches = true;
          } else {
            SC.watchState.set(key, { state: "retry", error: e.message });
            note(e.message);
          }
        }
        if (refreshWatches) loadTrade();
        SC.renderKey = "";
        scRenderResults();
      };
    });
    if (focused) {
      const el = box.querySelector(`[data-sc-f="${focused}"]`);
      if (el) el.focus();
    }
  }
  scRenderFooter(s);
}
function scRenderFooter(s) {
  const dur = Math.round(Number(s.duration_seconds) || 0);
  const est = s.estimate || {};
  let evalText = s.evaluation_used || s.evaluation || "";
  if (s.evaluation_used === "lazy" && est.requests) {
    evalText = `lazy (complete would need ≈${fmtInt(est.requests.complete)}; ${fmtInt(est.available)} available)`;
  }
  $("scFooter").textContent = [
    `Last run ${clock(s.finished_at || s.started_at)}`, `${fmtInt(s.scanned)} scanned`,
    `${fmtInt(s.errors)} errors`, `${fmtInt(s.na_symbols)} with n/a`,
    `${fmtInt(scRequests(s))} requests`, `${Math.floor(dur / 60)} m ${dur % 60} s`, evalText,
  ].filter(Boolean).join(" · ");
  const notes = (s.notes || []).slice();
  if (s.message) notes.unshift(s.message);
  if (s.synthetic) notes.push("Synthetic data: these are not real market prices.");
  const skipped = s.skipped || [];
  if (skipped.length) {
    notes.push(`${skipped.length} symbols skipped: ` + skipped.slice(0, 5)
      .map((x) => `${x.symbol} (${x.reason})`).join("; ") + (skipped.length > 5 ? "; …" : ""));
  }
  $("scNotes").innerHTML = notes.map((t) => `<li>${esc(t)}</li>`).join("");
}
$("scFilter").onchange = () => {
  $("scMinWrap").hidden = $("scFilter").value !== "atleast";
  scRenderResults();
};
$("scMinMet").oninput = () => scRenderResults();

/* ---------------------------------------------------------------- refresh */
async function refresh() {
  let st;
  try { st = await api("/api/status"); }
  catch (e) {
    $("pMode").textContent = "offline";
    $("pMode").className = "pill bad";
    note(e.message + (String(e.message).indexOf("X-API-Key") >= 0
      ? "  →  This is this app's own password, not a broker credential. " +
        "Read it with:  grep MATHERAN_API_KEY .env   then paste it top-right and press Use. " +
        "Or generate a fresh one from the Setup tab."
      : ""));
    STATUS_NOTE = true;
    return;
  }
  // Only clear what this poll put up. A message from a button press (an order that
  // was refused, say) stays until the next action instead of vanishing in seconds.
  if (STATUS_NOTE) { note(""); STATUS_NOTE = false; }
  SETTINGS_MODE = st.mode;
  RISK = st.risk || {};
  HAS_RULES = st.has_exit_rules !== false;
  $("pMode").textContent = st.mode.toUpperCase() + (st.mode === "live" ? " · REAL ORDERS" : " · simulated");
  $("pMode").className = "pill " + (st.mode === "live" ? "live" : "paper");
  $("pBroker").textContent = st.broker + (st.data_source && st.data_source !== st.broker
    ? " · data: " + st.data_source : "");
  $("pMarket").textContent = st.market_open_now ? "market open" : "market closed";
  $("pMarket").className = "pill " + (st.market_open_now ? "paper" : "");
  $("pAuth").textContent = st.authenticated ? "key required" : "UNAUTHENTICATED";
  $("pAuth").className = "pill " + (st.authenticated ? "" : "bad");
  $("pHalt").hidden = !st.halted;
  $("btnHalt").hidden = !!st.halted;
  $("btnResume").hidden = !st.halted;
  $("dirty").hidden = !st.broker_restart_required;
  $("dataErr").hidden = !st.data_api_error;
  if (st.data_api_error) $("dataErrMsg").textContent = st.data_api_error;
  $("tab-setup").querySelector(".dot")?.remove();
  if (st.broker_restart_required || !st.authenticated) {
    $("tab-setup").insertAdjacentHTML("beforeend", '<span class="dot" aria-hidden="true"></span>');
  }
  if (st.last_tick_error) { note("Last engine tick failed: " + st.last_tick_error); STATUS_NOTE = true; }

  if (TAB === "trade") loadTrade();
  if (TAB === "journal") loadJournal();
  if (TAB === "baskets") loadBaskets();
}

/* ------------------------------------------------------------------- boot */
fillTfSelects();
const initial = (location.hash || "").replace("#", "");
showTab(TABS.indexOf(initial) >= 0 ? initial : "trade");
refresh();
setInterval(refresh, 7000);
</script>
</body>
</html>
"""
