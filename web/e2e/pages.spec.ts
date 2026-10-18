import { expect, test } from "@playwright/test";

for (const [path, page] of [
  ["/", "portal"],
  ["/app/", "console"],
  ["/charts/", "charts"],
  ["/chain/", "chain"],
  ["/combo/?basket=abc", "combo"],
  ["/combo/?legs=x", "combo"],
] as const) {
  test(`${path} loads ${page}`, async ({ page: p }) => {
    await p.goto(path);
    await expect(p.locator("body")).toHaveAttribute("data-page", page);
    await expect(p).toHaveTitle(/Saidarshan/);
  });
}

test("the portal's CTA opens the app", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toHaveText("Sai Baba Live Darshan Portal");
  await expect(page.getByRole("link", { name: "Enter Saidarshan" })).toHaveAttribute("href", "/app");
});
