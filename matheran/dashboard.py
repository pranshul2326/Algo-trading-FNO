"""Single-file trading console. No build step, no external assets, no CDN."""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
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
</style>
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
    <p style="margin:8px 0 0">Nothing can be computed without candles — VWAP, RSI,
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
            <option value="BOTH">BOTH — buy above VWAP, sell below</option>
          </select>
        </label>
        <label class="f" for="qty">Quantity<input id="qty" type="number" min="1" step="1" value="1" required /></label>
        <label class="f" for="tf">Timeframe
          <select id="tf" data-tf="5"></select></label>
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
            <th class="l">Instrument</th><th class="l">Dir</th><th class="l">Kind</th><th>TF</th><th>Qty</th>
            <th class="l">State</th><th>LTP</th><th>VWAP</th><th>RSI</th><th>EMA(RSI,21)</th>
            <th>Supertrend</th><th>ADX</th>
            <th title="Every entry condition satisfied on the last closed candle; hover for each condition">Ready</th>
            <th>Entry</th><th>Stop</th><th>P&amp;L</th>
            <th class="l">Note</th><th></th>
          </tr></thead>
          <tbody id="watches"><tr><td colspan="18" class="mut">No watches yet.</td></tr></tbody>
        </table>
      </div>
    </section>
  </div>

  <!-- ============================= OPTIONS ============================= -->
  <div role="tabpanel" id="p-options" aria-labelledby="tab-options" hidden>
    <section class="panel">
      <h2>ATM and OTM scan</h2>
      <p class="sub">Current price, VWAP, RSI(21), EMA(RSI,21), EMA(21), Supertrend(21, 0.618)
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
            <th>LTP</th><th>VWAP</th><th>&gt;VWAP</th><th>RSI(21)</th><th>EMA(RSI,21)</th>
            <th>EMA(21)</th><th>Supertrend</th><th>ADX</th><th>Ready</th>
            <th class="l">Blocking condition</th><th>Actions</th>
          </tr></thead>
          <tbody id="chain"><tr><td colspan="14" class="mut">Press Scan.</td></tr></tbody>
        </table>
      </div>
    </section>
  </div>

  <!-- ============================= BASKETS ============================= -->
  <div role="tabpanel" id="p-baskets" aria-labelledby="tab-baskets" hidden>
    <section class="panel">
      <h2>New basket</h2>
      <p class="sub">A basket is a set of buy and sell legs sent together: a spread, a straddle,
        a pair trade. Each leg becomes a watch with its own stop, so every protection still
        applies. You can also build one from the <a href="/chain">option chain ↗</a> with its
        B / S buttons.</p>
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
        <strong>Combo</strong> opens the underlying, the combined premium with VWAP, EMAs and
        Supertrend, and the call and put legs on one 2 × 2 screen.
        <strong>Chart</strong> opens the combined basket value with indicators, beside its legs.</p>
      <div id="bkList" aria-live="polite"><p class="mut">No baskets yet.</p></div>
    </section>
  </div>

  <!-- ============================ STRATEGY ============================ -->
  <div role="tabpanel" id="p-strategy" aria-labelledby="tab-strategy" hidden>
    <section class="panel">
      <h2>Entry rules</h2>
      <p class="sub">All of these must hold on the last closed candle: price above VWAP,
        RSI above its 21-EMA, price above Supertrend, and ADX above the minimum for options.
        A SHORT (sell) watch uses the mirror image: price below VWAP, RSI below its 21-EMA and
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
            <th class="l" scope="col">Join</th><th class="l" scope="col">Indicator</th>
            <th class="l" scope="col">Condition</th><th class="l" scope="col">Compared with</th>
            <th class="l" scope="col">Checked</th><th scope="col"><span class="sr">Remove</span></th>
          </tr></thead>
          <tbody id="ruleRows"><tr><td colspan="6" class="l mut">Loading…</td></tr></tbody>
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
    throw new Error(typeof d === "string" ? d : JSON.stringify(d || res.statusText));
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
const TABS = ["setup", "trade", "options", "baskets", "strategy", "journal"];
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
  try { s = await api("/api/settings"); } catch (e) { note(e.message); return; }
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

function operandCell(i, side, o) {
  const choices = RULE_CAT.operands.filter((x) => side === "right" || x.left);
  const spec = operandSpec(o.ind) || { label: o.ind, params: [] };
  const what = side === "left" ? "indicator" : "compared with";
  const sel = `<select class="rsel" data-row="${i}" data-side="${side}"
      aria-label="Condition ${i + 1} ${what}">
    ${choices.map((x) => `<option value="${esc(x.id)}" ${x.id === o.ind ? "selected" : ""}>${esc(x.label)}</option>`).join("")}
    </select>`;
  const params = spec.params.map((p) => `<label class="pp">${esc(p.label)}
      <input type="text" inputmode="decimal" autocomplete="off" class="rp" size="5"
        data-row="${i}" data-side="${side}" data-key="${esc(p.key)}"
        value="${esc(o[p.key] == null ? p.default : o[p.key])}"
        aria-label="Condition ${i + 1} ${esc(spec.label)} ${esc(p.label.toLowerCase())}" /></label>`).join("");
  return `<div class="opnd">${sel}${params}</div>`;
}

function renderRules() {
  const tb = $("ruleRows");
  if (!RULE_CAT) return;
  if (!RULES.length) {
    tb.innerHTML = `<tr><td colspan="6" class="l mut">No indicator conditions: positions close
      on the stop, the target or the square-off only.</td></tr>`;
  } else {
    tb.innerHTML = RULES.map((r, i) => `<tr>
      <td class="l">${i === 0 ? '<span class="mut">IF</span>'
        : `<select class="rjoin" data-row="${i}" aria-label="How condition ${i + 1} joins the one above">
             <option value="AND" ${r.join === "AND" ? "selected" : ""}>AND</option>
             <option value="OR" ${r.join === "OR" ? "selected" : ""}>OR</option></select>`}</td>
      <td class="l">${operandCell(i, "left", r.left)}</td>
      <td class="l"><select class="rop" data-row="${i}" aria-label="Condition ${i + 1} comparison">
        ${RULE_CAT.comparators.map((c) => `<option value="${esc(c.id)}" ${c.id === r.op ? "selected" : ""}>${esc(c.label)}</option>`).join("")}
      </select></td>
      <td class="l">${operandCell(i, "right", r.right)}</td>
      <td class="l"><select class="ron" data-row="${i}" aria-label="When condition ${i + 1} is checked">
        ${RULE_CAT.on.map((o) => `<option value="${esc(o.id)}" ${o.id === r.on ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
      </select></td>
      <td><button type="button" class="sm rdel" data-row="${i}"
            aria-label="Remove condition ${i + 1}">✕</button></td>
    </tr>`).join("");
  }
  $("ruleAdd").disabled = RULES.length >= (RULE_CAT.max_rules || 12);

  const row = (el) => RULES[Number(el.dataset.row)];
  tb.querySelectorAll(".rsel").forEach((el) => {
    el.onchange = () => { row(el)[el.dataset.side] = freshOperand(el.value); rulesChanged(true); };
  });
  tb.querySelectorAll(".rp").forEach((el) => {
    el.oninput = () => {
      row(el)[el.dataset.side][el.dataset.key] = el.value.trim();
      el.classList.toggle("bad", el.value.trim() !== "" && !Number.isFinite(Number(el.value)));
      rulesChanged(false);
    };
  });
  tb.querySelectorAll(".rop").forEach((el) => { el.onchange = () => { row(el).op = el.value; rulesChanged(false); }; });
  tb.querySelectorAll(".rjoin").forEach((el) => { el.onchange = () => { row(el).join = el.value; rulesChanged(false); }; });
  tb.querySelectorAll(".ron").forEach((el) => { el.onchange = () => { row(el).on = el.value; rulesChanged(false); }; });
  tb.querySelectorAll(".rdel").forEach((el) => {
    el.onclick = () => { RULES.splice(Number(el.dataset.row), 1); rulesChanged(true); };
  });
}

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
               right: freshOperand("vwap"), on: "close" });
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
      `${limit ? "Limit" : "Market"} · ${out.product.toLowerCase()} · ${EXIT_TEXT[out.exit_mode]}\n\nSend it?`)) return;
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
    stop_loss_pct: Number($("sl").value) || null,
    target_pct: $("tp").value ? Number($("tp").value) : null,
    product: $("prod").value || null,
    exit_mode: $("exm").value || null,
  };
  try {
    await api("/api/watches", { method:"POST", body: JSON.stringify(body) });
    const how = {
      LONG: "It asks for approval to BUY when price is above VWAP, RSI above its 21-EMA and price above Supertrend.",
      SHORT: "It asks for approval to SELL when price is below VWAP, RSI below its 21-EMA and price below Supertrend.",
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
        <span>VWAP ${n(s.vwap)}</span>
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
  if (!list.length) { tb.innerHTML = '<tr><td colspan="18" class="mut">No watches yet.</td></tr>'; return; }
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
      <td>${esc(tfCode(w.timeframe_minutes))}</td><td>${w.quantity}</td>
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
async function loadExpiries() {
  try {
    const d = await api("/api/options/expiries?underlying=" + encodeURIComponent($("und").value));
    $("exp").innerHTML = '<option value="">nearest</option>' +
      (d.expiries || []).slice(0, 12).map((e) => `<option value="${esc(e)}">${esc(e)}</option>`).join("");
  } catch (e) { /* not fatal: nearest still works */ }
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
  });
  if ($("exp").value) q.set("expiry", $("exp").value);
  $("btnScan").disabled = true;
  $("chain").innerHTML = '<tr><td colspan="14" class="mut">Scanning…</td></tr>';
  try {
    const d = await api("/api/options/chain?" + q.toString());
    $("chainMeta").textContent =
      d.underlying + " " + d.expiry + " · " + d.reference + " " + d.reference_symbol + " " + n(d.spot) +
      " · ATM " + d.atm_strike + " · step " + d.strike_step + " · " + tfCode(d.timeframe_minutes) + " · ADX>" +
      n(d.adx_min,0) + " · " + d.above_vwap.length + " above VWAP · " + d.entry_ready.length + " entry-ready" +
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
        ${b.status === "open" ? "disabled" : ""}>Execute</button>
      <button type="button" class="sm danger" data-bkexit="${esc(b.id)}"
        ${b.open_legs ? "" : "disabled"}>Exit all</button>
      ${b.status === "watching"
        ? `<button type="button" class="sm" data-bkdisarm="${esc(b.id)}">Stop watching</button>`
        : `<button type="button" class="sm" data-bkarm="${esc(b.id)}" ${b.status === "open" ? "disabled" : ""}
             title="Each leg waits for its own entry signal and asks for approval separately">Watch legs</button>`}
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
