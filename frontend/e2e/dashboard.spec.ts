import { test, expect } from "@playwright/test";

// Authenticated via the project's storageState (see playwright.config.ts).
test("dashboard loads with the seeded fleet", async ({ page }) => {
  await page.goto("/");

  // Sidebar brand present.
  await expect(page.getByText("DBaaS").first()).toBeVisible();

  // The seeded fleet renders cards that link to the detail page (excludes "New instance").
  const instanceLinks = page.locator(
    'a[href^="/instances/"]:not([href$="/new"])',
  );
  await expect(instanceLinks.first()).toBeVisible();
});
