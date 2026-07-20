import { test, expect } from "@playwright/test";

test("instances list renders and opens an instance detail", async ({ page }) => {
  await page.goto("/instances");

  // Título da página.
  await expect(page.getByRole("heading", { name: /instances/i })).toBeVisible();

  // Abre o primeiro card de instância (exclui o link "New instance").
  const firstInstance = page
    .locator('a[href^="/instances/"]:not([href$="/new"])')
    .first();
  await expect(firstInstance).toBeVisible();
  await firstInstance.click();

  // A URL de detalhe carrega o UUID da instância.
  await expect(page).toHaveURL(/\/instances\/[0-9a-f-]{36}/);
});
