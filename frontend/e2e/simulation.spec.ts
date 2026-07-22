import { test, expect } from "@playwright/test";

// Fumaça do "demo ao vivo". Não roda o reel inteiro (~90s e altera a frota do
// ambiente), então o teste não clica em "Run live demo": verifica a página, o
// contrato "real vs. semeado" e que o estado consultado pelo banner chega ao
// browser.
test("demo page explains what is real and what is seeded", async ({ page }) => {
  await page.goto("/demo");

  await expect(page.getByRole("heading", { name: /live demo/i })).toBeVisible();
  await expect(page.getByText(/what is real/i)).toBeVisible();
  await expect(page.getByText(/what is seeded/i)).toBeVisible();

  // A timeline das fases é o coração da página.
  await expect(page.getByText(/traffic ramps up/i)).toBeVisible();
  await expect(page.getByText(/back up production/i)).toBeVisible();
});

test("sidebar reaches the simulation page", async ({ page }) => {
  await page.goto("/");
  // O item da sidebar é "Demo" (Nav.demo); o título da página é "Live demo".
  await page.getByRole("link", { name: /^demo$/i }).first().click();
  await expect(page).toHaveURL(/\/demo$/);
});

test("top bar exposes the live-demo control", async ({ page }) => {
  await page.goto("/");
  // Mesma posição, rótulo conforme o estado: parada → "Run live demo",
  // rodando → "Stop". É o atalho que torna o recurso descobrível.
  const control = page
    .locator("header")
    .getByRole("button", { name: /run live demo|stop/i });
  await expect(control).toBeVisible();
});

test("live-demo banner shows only while a run is in progress", async ({ page }) => {
  const status = await page.request.get("/api/v1/demo/simulation").catch(() => null);
  await page.goto("/");

  const banner = page.getByRole("status").filter({ hasText: /live demo/i });
  // A frota já nasce semeada (has_simulated_data é sempre true), então o banner
  // NÃO é dirigido por esse sinal: ele só aparece enquanto um reel roda, e aí
  // oferece o caminho para a página de detalhes.
  if (status?.ok()) {
    const body = await status.json();
    if (body.running) {
      await expect(banner).toBeVisible();
      await expect(banner.getByRole("link", { name: /details/i })).toBeVisible();
    } else {
      await expect(banner).toHaveCount(0);
    }
  }
});
