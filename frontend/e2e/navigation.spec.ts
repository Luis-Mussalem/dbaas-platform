import { test, expect } from "@playwright/test";

test("sidebar navigates to Instances", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /instances/i }).first().click();
  await expect(page).toHaveURL(/\/instances$/);
});

test("command palette opens with Ctrl+K and navigates", async ({ page }) => {
  await page.goto("/");

  // Abre o palette pelo atalho global.
  await page.keyboard.press("Control+K");
  const search = page.getByPlaceholder(/command or search/i);
  await expect(search).toBeVisible();

  // Busca uma página e navega com Enter.
  await search.fill("SQL");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/sql$/);
});

test("command palette closes with Escape", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Control+K");
  const search = page.getByPlaceholder(/command or search/i);
  await expect(search).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(search).toBeHidden();
});
