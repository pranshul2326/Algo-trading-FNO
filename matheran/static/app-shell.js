/* Saidarshan app shell: two navigation levels, per-workspace browser storage, the
   browser theme colour. Loaded in <head> of every application page, after
   ui-theme.js. No build step, no framework.

   window.SAIDARSHAN_CONTEXT (written by the server) = { workspace, view, nav, system }
     workspace  stock_intraday | option_buyer | option_seller | null (legacy page)
     view       the child view id, or null
     nav        [{ id, slug, label, views: [{ id, label, page, href }] }]

   window.SaidarshanStore   key(legacy) / migrate(legacy): localStorage per workspace
   window.SaidarshanShell   select(ws, view), lastView(ws), href(ws, view), announce(text),
                            onNavigate (set by the dashboard to handle its own views)
*/
(function () {
  "use strict";

  const CTX = window.SAIDARSHAN_CONTEXT || { workspace: null, view: null, nav: [] };
  const NAV = Array.isArray(CTX.nav) ? CTX.nav : [];
  const LAST_KEY = "saidarshan.app.v1";
  const THEME_COLOURS = { night: "#0f1216", light: "#ffffff" };

  /* ------------------------------------------------------------ storage */
  // Each workspace keeps its own copy of a page's saved state. The first time a
  // workspace opens a page, it starts from the original (pre-workspace) key, which is
  // copied, never moved: the old key stays for /charts, /chain and /combo, and for a
  // rollback. A marker records the copy so a later reset is not undone by it.
  const Store = {
    workspace: CTX.workspace || null,
    key(legacy) {
      return this.workspace ? "saidarshan.ws." + this.workspace + "." + legacy : legacy;
    },
    migrate(legacy) {
      if (!this.workspace) return false;
      const target = this.key(legacy);
      const marker = "saidarshan.migrated." + this.workspace + "." + legacy;
      try {
        if (localStorage.getItem(marker) !== null) return false;
        let copied = false;
        if (localStorage.getItem(target) === null) {
          const old = localStorage.getItem(legacy);
          if (old !== null) { localStorage.setItem(target, old); copied = true; }
        }
        localStorage.setItem(marker, new Date().toISOString());
        return copied;
      } catch (_error) { return false; }
    },
  };
  window.SaidarshanStore = Store;

  /* ---------------------------------------------------- last-visited views */
  function readLast() {
    try {
      const v = JSON.parse(localStorage.getItem(LAST_KEY) || "{}");
      return v && typeof v === "object" ? v : {};
    } catch (_error) { return {}; }
  }
  const wsOf = (id) => NAV.find((w) => w.id === id) || null;
  function lastView(ws) {
    const w = wsOf(ws);
    if (!w || !w.views.length) return null;
    const want = (readLast().views || {})[ws];
    return w.views.some((v) => v.id === want) ? want : w.views[0].id;
  }
  function href(ws, view) {
    const w = wsOf(ws);
    return w ? "/app/" + w.slug + (view ? "/" + view : "") : "/app";
  }
  function remember(ws, view) {
    if (!wsOf(ws) || !view) return;
    const last = readLast();
    last.workspace = ws;
    last.views = last.views || {};
    last.views[ws] = view;
    try { localStorage.setItem(LAST_KEY, JSON.stringify(last)); } catch (_error) {}
  }
  function lastWorkspace() {
    const ws = readLast().workspace;
    return wsOf(ws) ? ws : (NAV[0] && NAV[0].id) || null;
  }

  /* ----------------------------------------------------------- rendering */
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // The same markup the server renders on first load (app_pages.py), so the
  // dashboard can switch views without a reload.
  function viewTabsHtml(ws, view) {
    const w = wsOf(ws);
    if (!w) return "";
    const tabs = w.views.map((v, i) => {
      const on = v.id === view;
      const focusable = on || (!view && i === 0);
      return '<a role="tab" id="view-tab-' + esc(v.id) + '" data-ws-nav="view" data-ws="' +
        esc(w.id) + '" data-view="' + esc(v.id) + '" data-page="' + esc(v.page || "") +
        '" href="' + esc(v.href) + '" aria-selected="' + (on ? "true" : "false") +
        '" tabindex="' + (focusable ? "0" : "-1") + '"' + (on ? ' aria-controls="viewPanel"' : "") +
        ">" + esc(v.label) + "</a>";
    }).join("");
    return '<div class="ssh-views" role="tablist" aria-label="' + esc(w.label) +
      ' views" id="viewTabs">' + tabs + "</div>";
  }

  function select(ws, view) {
    const tabs = Array.from(document.querySelectorAll('#wsTabs [role="tab"]'));
    tabs.forEach((t, i) => {
      const on = t.dataset.ws === ws;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on || (!wsOf(ws) && i === 0) ? 0 : -1;
      if (on) t.setAttribute("aria-controls", "wsPanel"); else t.removeAttribute("aria-controls");
    });
    const panel = document.getElementById("wsPanel");
    const bar = document.getElementById("viewBar");
    if (panel) {
      if (wsOf(ws)) {
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", "ws-tab-" + ws);
        panel.removeAttribute("aria-label");
      } else {
        panel.setAttribute("role", "region");
        panel.removeAttribute("aria-labelledby");
        panel.setAttribute("aria-label", "System settings, applies to all workspaces");
      }
    }
    if (bar) {
      bar.innerHTML = viewTabsHtml(ws, view);
      bar.hidden = !wsOf(ws);
      const list = document.getElementById("viewTabs");
      if (list) wireTablist(list);
    }
    const vp = document.getElementById("viewPanel");
    if (vp) {
      if (wsOf(ws) && view) {
        vp.setAttribute("role", "tabpanel");
        vp.setAttribute("aria-labelledby", "view-tab-" + view);
      } else {
        vp.removeAttribute("role");
        vp.removeAttribute("aria-labelledby");
      }
    }
    const sys = document.getElementById("sysLink");
    if (sys) {
      if (CTX.system && !wsOf(ws)) sys.setAttribute("aria-current", "page");
      else sys.removeAttribute("aria-current");
    }
    if (wsOf(ws) && view) remember(ws, view);
    refreshWorkspaceHrefs();
    syncStickyOffset();
  }

  /* A workspace tab opens that workspace where it was left. */
  function refreshWorkspaceHrefs() {
    document.querySelectorAll('#wsTabs [role="tab"]').forEach((t) => {
      const ws = t.dataset.ws;
      t.href = href(ws, lastView(ws));
    });
  }

  /* ------------------------------------------------------------ keyboard */
  // Manual activation: arrows, Home and End move focus along the tabs (roving
  // tabindex); Enter or Space follows the focused tab's link. Moving focus never
  // navigates on its own, so arrowing past Chart does not load the chart page.
  function wireTablist(list) {
    if (list.dataset.wired) return;
    list.dataset.wired = "1";
    list.addEventListener("keydown", (ev) => {
      const tabs = Array.from(list.querySelectorAll('[role="tab"]'));
      const i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      let j = null;
      if (ev.key === "ArrowRight") j = (i + 1) % tabs.length;
      else if (ev.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
      else if (ev.key === "Home") j = 0;
      else if (ev.key === "End") j = tabs.length - 1;
      else if (ev.key === " " || ev.key === "Spacebar") {
        ev.preventDefault();
        tabs[i].click();
        return;
      }
      if (j === null) return;
      ev.preventDefault();
      tabs.forEach((t, k) => { t.tabIndex = k === j ? 0 : -1; });
      tabs[j].focus();
    });
    // Leaving the tab list hands the tab stop back to the selected tab.
    list.addEventListener("focusout", (ev) => {
      if (ev.relatedTarget && list.contains(ev.relatedTarget)) return;
      const tabs = Array.from(list.querySelectorAll('[role="tab"]'));
      const sel = tabs.find((t) => t.getAttribute("aria-selected") === "true") || tabs[0];
      tabs.forEach((t) => { t.tabIndex = t === sel ? 0 : -1; });
    });
  }

  /* ---------------------------------------------------------- navigation */
  // Plain links throughout: Cmd/Ctrl-click, middle-click and "open in new tab" are the
  // browser's. A plain click on a dashboard view is handed to the dashboard, which
  // swaps the view in place and records it in history.
  document.addEventListener("click", (ev) => {
    const a = ev.target && ev.target.closest ? ev.target.closest("a[data-ws-nav]") : null;
    if (!a) return;
    if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    if (typeof Shell.onNavigate === "function" && Shell.onNavigate(a, ev) === true) ev.preventDefault();
  });

  /* ------------------------------------------------------------- theming */
  function syncThemeColour() {
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = "theme-color";
      document.head.appendChild(meta);
    }
    const theme = document.documentElement.dataset.theme === "light" ? "light" : "night";
    meta.content = THEME_COLOURS[theme];
  }
  window.addEventListener("matheran-theme-change", syncThemeColour);

  /* ------------------------------------------------------------ announce */
  function announce(text) {
    const box = document.getElementById("sshLive");
    if (!box) return;
    box.textContent = "";
    window.setTimeout(() => { box.textContent = text; }, 30);
  }

  /* Heights of whatever part of the shell is sticky on this page: the view bar sits
     under the header, and scroll-padding keeps a focused field from hiding under both. */
  function syncStickyOffset() {
    const sticky = (el) => !!el && getComputedStyle(el).position === "sticky";
    const head = document.getElementById("shellHead");
    const bar = document.getElementById("viewBar");
    const headH = sticky(head) ? head.offsetHeight : 0;
    const barH = sticky(bar) && !bar.hidden ? bar.offsetHeight : 0;
    const root = document.documentElement.style;
    root.setProperty("--ssh-head-h", headH + "px");
    root.setProperty("--ssh-sticky", (headH + barH ? headH + barH + 8 : 0) + "px");
  }

  const Shell = {
    context: CTX, nav: NAV, select, lastView, lastWorkspace, href, announce,
    viewLabel(ws, view) {
      const w = wsOf(ws);
      const v = w && w.views.find((x) => x.id === view);
      return v ? v.label : "";
    },
    workspaceLabel(ws) { const w = wsOf(ws); return w ? w.label : ""; },
    onNavigate: null,
  };
  window.SaidarshanShell = Shell;

  function boot() {
    syncThemeColour();
    document.querySelectorAll('[role="tablist"].ssh-ws, [role="tablist"].ssh-views').forEach(wireTablist);
    if (CTX.workspace && CTX.view) remember(CTX.workspace, CTX.view);
    refreshWorkspaceHrefs();
    syncStickyOffset();
    window.addEventListener("resize", syncStickyOffset);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}());
