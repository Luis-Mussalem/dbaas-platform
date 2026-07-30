import { defineConfig, devices } from "@playwright/test";

// Smoke E2E tests over the critical path (login → dashboard → navigation →
// command palette → instance detail). Run against the already-running stack
// (docker compose up), so there is NO webServer here — they need the real
// backend to authenticate. Set E2E_BASE_URL to point at a different origin.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  // screenshots.ts regenerates the README images — it writes to docs/images/ and
  // is not a test, so it stays out of the smoke run and is invoked by path.
  testIgnore: /screenshots\.ts/,
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
    // 1) Logs in once and saves the session (HttpOnly cookies) to disk.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    // 2) Authenticated tests reuse that session.
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
