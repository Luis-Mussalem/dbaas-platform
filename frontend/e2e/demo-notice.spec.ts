import { test, expect } from "@playwright/test";

// A frota é gerada de propósito, e isso tem de estar CLARO na tela: uma faixa
// fixa em todo o dashboard + uma página "Sobre esta demo" com a explicação
// completa. O reel "Simular uso" foi removido — estes testes fixam esse contrato.

test("the demo notice is visible and links to the About page", async ({ page }) => {
  await page.goto("/");

  const notice = page.getByRole("note").filter({ hasText: /demo environment/i });
  await expect(notice).toBeVisible();
  await notice.getByRole("link", { name: /learn more/i }).click();

  await expect(page).toHaveURL(/\/demo$/);
  await expect(page.getByRole("heading", { name: /about this demo/i })).toBeVisible();
});

test("the About page explains what is real and what is generated", async ({ page }) => {
  await page.goto("/demo");

  await expect(page.getByText(/what is real/i)).toBeVisible();
  await expect(page.getByText(/what is generated/i)).toBeVisible();
  // A jornada do botão removido faz parte da documentação na tela.
  await expect(page.getByText(/simulate usage/i)).toBeVisible();
});

test("the removed simulation endpoints are gone", async ({ page }) => {
  const res = await page.request
    .get("/api/v1/demo/simulation")
    .catch(() => null);
  // 404 (rota removida) — nunca 200.
  if (res) expect(res.status()).toBe(404);
});
