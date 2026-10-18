"""Saidarshan page assembly: the landing page, and the app shell around every page.

The shell is two navigation levels - the three workspaces, then the selected
workspace's child views - rendered here on first load and kept current by
/static/app-shell.js. The dashboard views are one document; the Chart, Option Chain
and Combo Chart views are the existing full-page screens, served inside the same
shell with their workspace as context. No iframes.
"""

from __future__ import annotations

import json
import re
from html import escape

from . import workspaces as ws_mod

BRAND = "Saidarshan"
THEME_COLOUR = "#0f1216"   # night; app-shell.js follows the chosen theme after load


def nav_context(ws: str | None, view: str | None, *, system: bool = False) -> dict:
    return {"workspace": ws, "view": view, "system": system, "nav": ws_mod.navigation(),
            "legacyHashes": ws_mod.legacy_hash_paths()}


def _json_script(data: dict) -> str:
    # Inline JSON must not be able to close the script element.
    text = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return f"<script>window.SAIDARSHAN_CONTEXT = {text};</script>"


def head_assets(ws: str | None, view: str | None, *, system: bool = False) -> str:
    return (
        f'<meta name="theme-color" content="{THEME_COLOUR}" />\n'
        '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />\n'
        '<link rel="stylesheet" href="/static/app-shell.css" />\n'
        + _json_script(nav_context(ws, view, system=system)) + "\n"
        '<script src="/static/app-shell.js"></script>\n'
    )


def ws_tabs_html(ws: str | None) -> str:
    tabs = []
    for i, w in enumerate(ws_mod.navigation()):
        on = w["id"] == ws
        focusable = on or (ws is None and i == 0)
        controls = ' aria-controls="wsPanel"' if on else ""
        tabs.append(
            f'<a role="tab" id="ws-tab-{w["id"]}" data-ws-nav="ws" data-ws="{w["id"]}" '
            f'href="/app/{w["slug"]}" aria-selected="{"true" if on else "false"}" '
            f'tabindex="{"0" if focusable else "-1"}"{controls}>{escape(w["label"])}</a>'
        )
    return ('<div class="ssh-ws" role="tablist" aria-label="Workspaces" id="wsTabs">'
            + "".join(tabs) + "</div>")


def view_tabs_html(ws: str | None, view: str | None) -> str:
    if ws not in ws_mod.WORKSPACES:
        return ""
    w = next(n for n in ws_mod.navigation() if n["id"] == ws)
    tabs = []
    for i, v in enumerate(w["views"]):
        on = v["id"] == view
        focusable = on or (view is None and i == 0)
        controls = ' aria-controls="viewPanel"' if on else ""
        tabs.append(
            f'<a role="tab" id="view-tab-{v["id"]}" data-ws-nav="view" data-ws="{ws}" '
            f'data-view="{v["id"]}" data-page="{v["page"] or ""}" href="{v["href"]}" '
            f'aria-selected="{"true" if on else "false"}" '
            f'tabindex="{"0" if focusable else "-1"}"{controls}>{escape(v["label"])}</a>'
        )
    return (f'<div class="ssh-views" role="tablist" aria-label="{escape(w["label"])} views" '
            f'id="viewTabs">' + "".join(tabs) + "</div>")


def brand_html() -> str:
    return ('<a class="ssh-brand" href="/" aria-label="Saidarshan home">'
            '<span class="ssh-mark" aria-hidden="true"></span>'
            f'<span translate="no">{BRAND}</span></a>')


def title_for(ws: str | None, view: str | None, fallback: str) -> str:
    if ws in ws_mod.WORKSPACES and view:
        label = dict(ws_mod.WORKSPACES[ws]["views"]).get(view, fallback)
        return f"{label} · {ws_mod.label_of(ws)} · {BRAND}"
    return f"{fallback} · {BRAND}"


# ------------------------------------------------------------------ full pages
_PAGE_LABELS = {"chart": "Chart", "option-chain": "Option Chain", "combo-chart": "Combo Chart"}


def page_in_shell(html: str, ws: str | None, view: str) -> str:
    """One of the full-page screens (charts, option chain, combo) inside the shell.

    `ws` None is a legacy route (/charts, /chain, /combo): the same screen with its
    original browser storage and no workspace selected.
    """
    label = _PAGE_LABELS.get(view, view)
    title = title_for(ws, view, label)
    html = re.sub(r"<title>.*?</title>", f"<title>{escape(title)}</title>", html, count=1,
                  flags=re.S)
    html = html.replace("</head>", head_assets(ws, view) + "</head>", 1)

    if ws in ws_mod.WORKSPACES:
        bar = view_tabs_html(ws, view)
        open_panels = (
            f'<div id="wsPanel" class="ssh-wspanel" role="tabpanel" aria-labelledby="ws-tab-{ws}">'
            f'<div id="viewBar" class="ssh-viewbar">{bar}</div>'
            f'<div id="viewPanel" class="ssh-viewpanel" role="tabpanel" '
            f'aria-labelledby="view-tab-{view}" tabindex="-1">'
        )
    else:
        note = ("Original view with its original layout. Choose a workspace above to "
                "keep separate charts, settings and drawings per workspace.")
        open_panels = (
            '<div id="wsPanel" class="ssh-wspanel" role="region" aria-label="Legacy view">'
            f'<div id="viewBar" class="ssh-viewbar"><p class="ssh-legacy-note">{note}</p></div>'
            '<div id="viewPanel" class="ssh-viewpanel" tabindex="-1">'
        )
    shell = (
        '<a class="ssh-skip" href="#viewPanel">Skip to content</a>'
        '<header class="ssh" aria-label="Saidarshan">'
        '<div class="ssh-row">'
        + brand_html() + ws_tabs_html(ws) +
        '<div class="ssh-grow"></div>'
        '<div class="ssh-global" role="group" aria-label="Applies to all workspaces">'
        '<a id="sysLink" class="ssh-sys" href="/app/system" '
        'title="Mode, broker, credentials and engine caps: applies to all workspaces">System</a>'
        "</div></div></header>"
        '<p id="sshLive" class="ssh-sr" role="status" aria-live="polite"></p>'
        + open_panels
    )
    html = html.replace("<body>", '<body class="ssh-page">' + shell, 1)
    html = html.replace("</body>", "</div></div></body>", 1)
    return html


# --------------------------------------------------------------- the dashboard
def shell_html(html: str, ws: str | None = None, view: str | None = None, *,
               system: bool = False) -> str:
    """The dashboard document, with the shell rendered for the requested view."""
    if system:
        title = f"System settings · {BRAND}"
    elif ws in ws_mod.WORKSPACES and view:
        title = title_for(ws, view, "")
    elif ws in ws_mod.WORKSPACES:
        title = f"{ws_mod.label_of(ws)} · {BRAND}"
    else:
        title = BRAND
    if ws in ws_mod.WORKSPACES:
        ws_attrs = f'role="tabpanel" aria-labelledby="ws-tab-{ws}"'
    else:
        ws_attrs = 'role="region" aria-label="System settings, applies to all workspaces"'
    if ws in ws_mod.WORKSPACES and view:
        view_attrs = f'role="tabpanel" aria-labelledby="view-tab-{view}"'
    else:
        view_attrs = ""
    return (
        html.replace("__SSH_TITLE__", escape(title), 1)
        .replace("<!--SSH:HEAD-->", head_assets(ws, view, system=system), 1)
        .replace("<!--SSH:BRAND-->", brand_html(), 1)
        .replace("<!--SSH:WSTABS-->", ws_tabs_html(ws), 1)
        .replace("<!--SSH:VIEWTABS-->", view_tabs_html(ws, view), 1)
        .replace("__SSH_VIEWBAR_HIDDEN__", "" if ws in ws_mod.WORKSPACES else "hidden", 1)
        .replace("__SSH_WSPANEL_ATTRS__", ws_attrs, 1)
        .replace("__SSH_VIEWPANEL_ATTRS__", view_attrs, 1)
    )


# ------------------------------------------------------------ the landing page
def landing_html() -> str:
    hashes = json.dumps(ws_mod.legacy_hash_paths())
    return LANDING_HTML.replace("__LEGACY_HASHES__", hashes.replace("</", "<\\/"))


LANDING_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="/static/ui-theme.js"></script>
<script>
  // Old dashboard bookmarks (/#trade, /#scanner, ...) open the same view in the app.
  (function () {
    var map = __LEGACY_HASHES__;
    function forward() {
      var key = (location.hash || "").replace(/^#/, "");
      if (key && Object.prototype.hasOwnProperty.call(map, key)) {
        location.replace(map[key]);
      }
    }
    forward();
    window.addEventListener("hashchange", forward);
  }());
</script>
<title>Sai Baba Live Darshan Portal · Saidarshan</title>
<meta name="description" content="Saidarshan: Shraddha and Saburi, faith and patience." />
<meta name="theme-color" content="#0b0c0e" />
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />
<style>
  :root, :root[data-theme="night"] {
    --bg:#0b0c0e; --surface:#121418; --surface-2:#171a1f; --line:#24282f; --line-soft:#1b1e23;
    --ink:#f2efe8; --body:#b9b4aa; --mute:#8c877d; --accent:#e3a33b; --accent-ink:#1a1206;
    --glow:rgba(227,163,59,.22); --glow-2:rgba(214,120,44,.12); --focus:#7cb4ff;
    --shadow:0 1px 1px rgba(0,0,0,.25), 0 10px 30px -10px rgba(0,0,0,.55);
  }
  :root[data-theme="light"] {
    --bg:#fbfaf7; --surface:#ffffff; --surface-2:#f6f3ec; --line:#e7e1d6; --line-soft:#efeae1;
    --ink:#1d1a15; --body:#55504a; --mute:#7a746b; --accent:#a85d08; --accent-ink:#ffffff;
    --glow:rgba(227,163,59,.28); --glow-2:rgba(214,120,44,.14); --focus:#0a58ca;
    --shadow:0 1px 1px rgba(30,20,0,.04), 0 10px 30px -12px rgba(60,40,0,.18);
  }
  * { box-sizing:border-box; }
  html { background:var(--bg); color-scheme:dark; }
  :root[data-theme="light"] { color-scheme:light; }
  body { margin:0; min-height:100vh; display:flex; flex-direction:column; background:var(--bg);
    color:var(--ink); font:16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing:antialiased; }
  a { color:inherit; }
  :focus-visible { outline:2px solid var(--focus); outline-offset:3px; border-radius:6px; }
  .skip { position:absolute; left:12px; top:-60px; background:var(--ink); color:var(--bg);
    padding:10px 14px; border-radius:6px; font-weight:600; text-decoration:none; z-index:10; }
  .skip:focus { top:12px; }

  .top { display:flex; align-items:center; justify-content:space-between; gap:16px;
    max-width:1120px; width:100%; margin:0 auto; padding:18px 24px; }
  .brand { display:inline-flex; align-items:center; gap:10px; text-decoration:none;
    font-weight:650; letter-spacing:-.01em; }
  .mark { width:22px; height:22px; border-radius:50%; flex:none;
    background:radial-gradient(circle at 50% 62%, #fff4d6 0 18%, transparent 19%),
               radial-gradient(circle at 50% 55%, #f7c35f 0 42%, #d9822b 70%, #9c4a12 100%);
    box-shadow:0 0 0 1px var(--line), 0 0 16px var(--glow); }
  .theme { display:flex; align-items:center; gap:8px; color:var(--mute); font-size:13px; }
  .theme select { font:inherit; font-size:14px; color:var(--ink); background:var(--surface);
    border:1px solid var(--line); border-radius:6px; padding:6px 10px; min-height:36px; }

  main { flex:1; display:grid; place-items:center; padding:24px; }
  .hero { position:relative; width:100%; max-width:1120px; display:grid; place-items:center;
    text-align:center; padding:72px 24px 88px; border:1px solid var(--line-soft);
    border-radius:16px; background:linear-gradient(180deg, var(--surface) 0%, var(--bg) 100%);
    box-shadow:var(--shadow); overflow:hidden; isolation:isolate; }
  /* An abstract light, not a picture: a still diya-like glow and a faint mandala. */
  .aura { position:absolute; inset:-20% -10% auto; height:120%; z-index:-1; pointer-events:none;
    background:radial-gradient(40% 32% at 50% 38%, var(--glow) 0%, transparent 70%),
               radial-gradient(70% 50% at 50% 40%, var(--glow-2) 0%, transparent 75%); }
  .mandala { position:absolute; top:50%; left:50%; width:min(720px, 120vw); aspect-ratio:1;
    transform:translate(-50%, -54%); z-index:-1; opacity:.5; pointer-events:none; }
  .mandala circle { fill:none; stroke:var(--line); }
  .eyebrow { font:500 12px/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing:.14em;
    text-transform:uppercase; color:var(--accent); margin:0 0 18px; }
  h1 { margin:0; font-size:clamp(34px, 6vw, 56px); line-height:1.05; letter-spacing:-.035em;
    font-weight:650; max-width:16ch; text-wrap:balance; }
  .devotion { margin:22px 0 6px; font-size:clamp(18px, 2.4vw, 22px); color:var(--ink);
    font-weight:500; letter-spacing:-.01em; }
  .support { margin:0; color:var(--body); max-width:44ch; text-wrap:pretty; }
  .cta { margin-top:36px; display:inline-flex; align-items:center; gap:10px; min-height:48px;
    padding:0 26px; border-radius:999px; background:var(--ink); color:var(--bg);
    font-weight:600; text-decoration:none; box-shadow:0 0 0 1px var(--ink), 0 8px 24px -8px var(--glow);
    transition:transform .15s ease, box-shadow .15s ease; }
  .cta:hover { transform:translateY(-1px); box-shadow:0 0 0 1px var(--ink), 0 12px 30px -8px var(--glow); }
  .cta:active { transform:translateY(0); }
  .cta svg { width:16px; height:16px; }

  footer { max-width:1120px; width:100%; margin:0 auto; padding:20px 24px 28px; display:flex;
    justify-content:space-between; gap:12px; flex-wrap:wrap; color:var(--mute); font-size:13px;
    border-top:1px solid var(--line-soft); }
  footer a { color:var(--body); text-underline-offset:3px; }

  @media (max-width:640px) {
    .top { padding:14px 16px; }
    .hero { padding:56px 18px 64px; border-radius:12px; }
    .cta { width:100%; justify-content:center; min-height:52px; }
    .theme select { font-size:16px; min-height:44px; }
  }
  @media (prefers-reduced-motion:no-preference) {
    .aura { animation:breathe 9s ease-in-out infinite alternate; }
    @keyframes breathe { from { opacity:.75; transform:scale(1); } to { opacity:1; transform:scale(1.04); } }
  }
  @media (prefers-reduced-motion:reduce) {
    .cta { transition:none; }
  }
</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <a class="brand" href="/" aria-label="Saidarshan home">
    <span class="mark" aria-hidden="true"></span><span translate="no">Saidarshan</span></a>
  <label class="theme" for="themeSelect">Theme
    <select id="themeSelect" data-theme-select><option value="night">Night</option><option value="light">Light</option></select>
  </label>
</header>
<main id="main">
  <section class="hero" aria-labelledby="title">
    <div class="aura" aria-hidden="true"></div>
    <svg class="mandala" viewBox="0 0 200 200" aria-hidden="true" focusable="false">
      <circle cx="100" cy="100" r="30" stroke-width=".35" />
      <circle cx="100" cy="100" r="48" stroke-width=".3" />
      <circle cx="100" cy="100" r="66" stroke-width=".25" stroke-dasharray="1 3" />
      <circle cx="100" cy="100" r="84" stroke-width=".2" />
      <circle cx="100" cy="100" r="98" stroke-width=".15" stroke-dasharray=".5 4" />
    </svg>
    <p class="eyebrow" translate="no">Saidarshan</p>
    <h1 id="title">Sai Baba Live Darshan Portal</h1>
    <p class="devotion">Shraddha &amp; Saburi — Faith &amp; Patience.</p>
    <p class="support">May Sai guide every step with patience, clarity &amp; peace.</p>
    <a class="cta" href="/app">Enter Saidarshan
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M3 8h9m-3.5-4L12 8l-3.5 4"
        fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></a>
  </section>
</main>
<footer>
  <span><span translate="no">Saidarshan</span> · Shraddha &amp; Saburi</span>
  <a href="/app">Enter Saidarshan</a>
</footer>
<script>
  // The browser colour follows the chosen theme.
  (function () {
    function sync() {
      var light = document.documentElement.dataset.theme === "light";
      var meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.content = light ? "#fbfaf7" : "#0b0c0e";
    }
    sync();
    window.addEventListener("matheran-theme-change", sync);
  }());
</script>
</body>
</html>
"""


NOT_FOUND_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="/static/ui-theme.js"></script>
<title>Not found · Saidarshan</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />
<link rel="stylesheet" href="/static/ui-theme.css" />
<style>
  body { margin:0; min-height:100vh; display:grid; place-items:center; padding:24px;
    font:15px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width:480px; text-align:center; }
  h1 { font-size:24px; letter-spacing:-.02em; margin:0 0 8px; }
  p { color:var(--muted); margin:0 0 20px; }
  a { display:inline-flex; gap:.3em; min-height:44px; align-items:center; padding:0 18px;
    border-radius:999px; border:1px solid var(--line); color:var(--text); text-decoration:none;
    font-weight:600; }
  a:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
</style>
</head>
<body>
<main>
  <h1>This view does not exist</h1>
  <p>The workspace or view in the address is not one of <span translate="no">Saidarshan</span>'s.</p>
  <a href="/app"><span>Open</span><span translate="no">Saidarshan</span></a>
</main>
</body>
</html>
"""
