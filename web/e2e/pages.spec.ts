import { expect, test } from "@playwright/test";

for (const [path, page] of [
  ["/", "console"],
  ["/charts/", "charts"],
  ["/chain/", "chain"],
  ["/combo/?basket=abc", "combo"],
  ["/combo/?legs=x", "combo"],
] as const) {
  test(`${path} loads ${page}`, async ({ page: p }) => {
    await p.goto(path);
    await expect(p.locator("body")).toHaveAttribute("data-page", page);
  });
}
