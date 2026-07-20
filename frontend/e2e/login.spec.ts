import { test, expect } from "@playwright/test";
import { DEMO_EMAIL, DEMO_PASSWORD } from "./helpers";

// Estes testes exercitam a própria tela de login, então rodam SEM a sessão
// salva (contexto anônimo sobrescrevendo o storageState do projeto).
test.use({ storageState: { cookies: [], origins: [] } });

test("login page renders the form", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator("#username")).toBeVisible();
  await expect(page.locator("#password")).toBeVisible();
  await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
});

test("rejects invalid credentials", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#username").fill("nobody@example.com");
  await page.locator("#password").fill("wrong-password");
  await page.getByRole("button", { name: /sign in/i }).click();

  // Continua na tela de login e mostra um erro — não navega para o painel.
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("alert").or(page.locator("p.text-danger"))).toBeVisible();
});

test("signs in with the demo account and reaches the dashboard", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#username").fill(DEMO_EMAIL);
  await page.locator("#password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.waitForURL("**/");
  await expect(page.getByRole("link", { name: /instances/i }).first()).toBeVisible();
});
