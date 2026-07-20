import { test as setup, expect } from "@playwright/test";
import { DEMO_EMAIL, DEMO_PASSWORD } from "./helpers";

const AUTH_FILE = "e2e/.auth/user.json";

// Faz login uma única vez e persiste a sessão. Os tokens vivem em cookies
// HttpOnly (invisíveis ao JS), mas o storageState do Playwright os captura do
// contexto do navegador — então os demais specs herdam a sessão sem repetir o
// fluxo de login a cada teste.
setup("authenticate", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#username").fill(DEMO_EMAIL);
  await page.locator("#password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  // Login bem-sucedido redireciona para o painel (raiz).
  await page.waitForURL("**/");
  await expect(page.getByText("DBaaS").first()).toBeVisible();

  await page.context().storageState({ path: AUTH_FILE });
});
