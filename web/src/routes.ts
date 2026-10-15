export type Page = "console" | "charts" | "chain" | "combo" | "unknown";

/** Map a URL pathname to the page name used by the Python app routes. */
export function pageFromPath(pathname: string): Page {
  const p = pathname.replace(/\/(index\.html)?$/, "") || "/";
  switch (p) {
    case "/":
      return "console";
    case "/charts":
    case "/chain":
    case "/combo":
      return p.slice(1) as Page;
    default:
      return "unknown";
  }
}
