import { defineConfig, devices } from "@playwright/test";

// Testes E2E de fumaça sobre o caminho crítico (login → painel → navegação →
// command palette → detalhe da instância). Rodam contra o stack em execução
// (docker compose up), então NÃO há webServer aqui — eles precisam do backend
// real para autenticar. Ajuste E2E_BASE_URL para apontar para outra origem.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    // 1) Faz login uma vez e salva a sessão (cookies HttpOnly) em disco.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    // 2) Testes autenticados reusam essa sessão.
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/user.json",
      },
      dependencies: ["setup"],
    },
  ],
});
