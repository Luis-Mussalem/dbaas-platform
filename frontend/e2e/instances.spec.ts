import { test, expect } from "@playwright/test";

test("instances list renders and opens an instance detail", async ({ page }) => {
  await page.goto("/instances");

  // Page title.
  await expect(page.getByRole("heading", { name: /instances/i })).toBeVisible();

  // Opens the first instance card (excludes the "New instance" link).
  const firstInstance = page
    .locator('a[href^="/instances/"]:not([href$="/new"])')
    .first();
  await expect(firstInstance).toBeVisible();
  await firstInstance.click();

  // The detail URL carries the instance's UUID.
  await expect(page).toHaveURL(/\/instances\/[0-9a-f-]{36}/);
});
