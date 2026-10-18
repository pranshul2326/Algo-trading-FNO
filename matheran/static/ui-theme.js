(function () {
  "use strict";

  const KEY = "matheranTheme.v1";
  const THEMES = new Set(["night", "light"]);

  function storedTheme() {
    try {
      const value = localStorage.getItem(KEY);
      return THEMES.has(value) ? value : "night";
    } catch (_error) {
      return "night";
    }
  }

  function applyTheme(theme, persist, announce) {
    const value = THEMES.has(theme) ? theme : "night";
    document.documentElement.dataset.theme = value;
    document.documentElement.style.colorScheme = value === "light" ? "light" : "dark";
    if (persist) {
      try { localStorage.setItem(KEY, value); } catch (_error) {}
    }
    document.querySelectorAll("[data-theme-select]").forEach(function (select) {
      select.value = value;
      select.setAttribute("aria-label", "Colour theme: " + (value === "light" ? "Light" : "Night"));
    });
    if (announce) {
      window.dispatchEvent(new CustomEvent("matheran-theme-change", { detail: { theme: value } }));
    }
    return value;
  }

  applyTheme(storedTheme(), false, false);
  window.MatheranTheme = { key: KEY, current: function () {
    return document.documentElement.dataset.theme || "night";
  }, apply: applyTheme };

  function wireSelectors() {
    applyTheme(document.documentElement.dataset.theme || storedTheme(), false, false);
    document.querySelectorAll("[data-theme-select]").forEach(function (select) {
      select.addEventListener("change", function () { applyTheme(select.value, true, true); });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wireSelectors);
  else wireSelectors();

  window.addEventListener("storage", function (event) {
    if (event.key === KEY && THEMES.has(event.newValue)) applyTheme(event.newValue, false, true);
  });
}());
