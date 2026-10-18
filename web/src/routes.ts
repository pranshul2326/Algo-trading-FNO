export type Page = "portal" | "console" | "charts" | "chain" | "combo" | "unknown";

/** Map a URL pathname to the page name used by the Python app routes:
 *  "/" is the Saidarshan landing portal and "/app" the console. The console's
 *  workspace views (/app/<workspace>/<view>) exist only in the Python app. */
export function pageFromPath(pathname: string): Page {
  const p = pathname.replace(/\/(index\.html)?$/, "") || "/";
  switch (p) {
    case "/":
      return "portal";
    case "/app":
      return "console";
    case "/charts":
    case "/chain":
    case "/combo":
      return p.slice(1) as Page;
    default:
      return "unknown";
  }
}
