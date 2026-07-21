import { test, expect } from "@playwright/test";

// Fumaça da simulação de uso. Não roda o roteiro inteiro (são ~6 min de relógio
// real): verifica a página, o contrato "real vs. semeado" e que o estado
// consultado pelo banner chega ao browser. Iniciar/parar a simulação de verdade
// alteraria a frota do ambiente, então o teste não clica em "Simular uso".
test("demo page explains what is real and what is seeded", async ({ page }) => {
  await page.goto("/demo");

  await expect(page.getByRole("heading", { name: /simulate usage/i })).toBeVisible();
  await expect(page.getByText(/what is real/i)).toBeVisible();
  await expect(page.getByText(/what is seeded/i)).toBeVisible();

  // A timeline das fases é o coração da página.
  await expect(page.getByText(/traffic ramps up/i)).toBeVisible();
  await expect(page.getByText(/back up production/i)).toBeVisible();
});

test("sidebar reaches the simulation page", async ({ page }) => {
  await page.goto("/");
  // O item da sidebar é "Demo" (Nav.demo); o título da página é "Simulate usage".
  await page.getByRole("link", { name: /^demo$/i }).first().click();
  await expect(page).toHaveURL(/\/demo$/);
});

test("top bar exposes the simulation control", async ({ page }) => {
  await page.goto("/");
  // Mesma posição, rótulo conforme o estado: parada → "Simulate usage",
  // rodando → "Stop". É o atalho que torna o recurso descobrível.
  const control = page
    .locator("header")
    .getByRole("button", { name: /simulate usage|stop/i });
  await expect(control).toBeVisible();
});

test("simulated-data banner reflects the fleet state", async ({ page }) => {
  const status = await page.request.get("/api/v1/demo/simulation").catch(() => null);
  await page.goto("/");

  const banner = page.getByRole("status").filter({ hasText: /simulated usage/i });
  // O banner só existe quando há simulação em curso ou dado semeado presente —
  // e quando existe, oferece o caminho para a página de detalhes.
  if (status?.ok()) {
    const body = await status.json();
    if (body.running || body.has_simulated_data) {
      await expect(banner).toBeVisible();
      await expect(banner.getByRole("link", { name: /details/i })).toBeVisible();
    } else {
      await expect(banner).toHaveCount(0);
    }
  }
});
