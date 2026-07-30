import { test, expect, type Page } from "@playwright/test";

// Regenerates the README screenshots in docs/images/ against the running demo
// stack. Not part of the smoke suite — run it explicitly:
//
//   docker run --rm --network host -v "$PWD/..":/repo -w /repo/frontend \
//     mcr.microsoft.com/playwright:v1.61.1-noble \
//     npx playwright test --config=playwright.screenshots.config.ts
//
// The viewport matches the width the existing images were captured at (~1860px)
// so the set stays visually consistent as it is regenerated.
const OUT = process.env.SHOTS_OUT ?? "../docs/images";

test.use({
  viewport: { width: 1860, height: 930 },
  // The captured PNGs are 2x so they stay sharp on a HiDPI screen; GitHub scales
  // them down to the README column width.
  deviceScaleFactor: 2,
});

// The UI is bilingual and the set must be English throughout (docs/images/README.md).
test.beforeEach(async ({ context }) => {
  await context.addCookies([
    { name: "NEXT_LOCALE", value: "en", url: "http://localhost:3000" },
  ]);
});

// Charts animate in and the fleet cards fetch their summary after mount, so a
// bare load event is not enough — wait for the network to settle, then let the
// entrance animations finish before the shutter.
async function settle(page: Page, ms = 2500) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(ms);
}

test("dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your databases" })).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/dashboard.png` });
});

test("instances", async ({ page }) => {
  await page.goto("/instances");
  await settle(page);
  await page.screenshot({ path: `${OUT}/instances.png` });
});

test("instance overview and metrics", async ({ page }) => {
  await page.goto("/instances");
  await settle(page, 1500);

  // Exclude the "New instance" link, which shares the /instances/ href prefix.
  const card = page
    .locator("a[href^='/instances/']:not([href='/instances/new'])")
    .first();
  await card.click();
  await page.waitForURL(/\/instances\/[0-9a-f-]{36}/);
  await settle(page);
  await page.screenshot({ path: `${OUT}/instance-view.png` });

  await page.getByRole("button", { name: /^metrics$/i }).click();
  await settle(page);
  await page.screenshot({ path: `${OUT}/instance-detail.png` });
});

test("sql console", async ({ page }) => {
  await page.goto("/sql");
  await settle(page, 1500);

  const editor = page.locator("textarea").first();
  await editor.click();
  // No trailing semicolon: the console rejects it, since it only accepts a single
  // SELECT statement.
  await editor.fill(
    "SELECT category, brand, COUNT(*) AS orders, SUM(amount) AS revenue " +
      "FROM sales GROUP BY category, brand ORDER BY revenue DESC LIMIT 20",
  );
  await page.getByRole("button", { name: /run/i }).first().click();
  await settle(page);
  await page.screenshot({ path: `${OUT}/sql-console.png` });
});

test("audit log", async ({ page }) => {
  await page.goto("/audit");
  await settle(page);
  await page.screenshot({ path: `${OUT}/logs.png` });
});

test("employees and rbac", async ({ page }) => {
  await page.goto("/admin/users");
  await settle(page);
  await page.screenshot({ path: `${OUT}/admin-users.png` });
});
