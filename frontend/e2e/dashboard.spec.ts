import { test, expect } from "@playwright/test";

// Autenticado via storageState do projeto (ver playwright.config.ts).
test("dashboard loads with the seeded fleet", async ({ page }) => {
  await page.goto("/");

  // Marca da sidebar presente.
  await expect(page.getByText("DBaaS").first()).toBeVisible();

  // A frota semeada rende cards que linkam para o detalhe (exclui "New instance").
  const instanceLinks = page.locator(
    'a[href^="/instances/"]:not([href$="/new"])',
  );
  await expect(instanceLinks.first()).toBeVisible();
});
