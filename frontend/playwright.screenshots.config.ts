import { defineConfig, devices } from "@playwright/test";

// Dedicated config for regenerating the README images (see e2e/screenshots.ts).
// It is separate from playwright.config.ts because that one deliberately ignores
// screenshots.ts: the capture writes into docs/images/ and must never run as part
// of the smoke suite.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  // The captures share one fleet and click through it — keep them sequential so
  // the shots are deterministic.
  workers: 1,
  reporter: "list",
  use: { baseURL: BASE_URL },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      testMatch: /screenshots\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/user.json" },
      dependencies: ["setup"],
    },
  ],
});
