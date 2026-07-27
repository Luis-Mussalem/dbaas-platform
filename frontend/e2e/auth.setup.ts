import { test as setup, expect } from "@playwright/test";
import { DEMO_EMAIL, DEMO_PASSWORD } from "./helpers";

const AUTH_FILE = "e2e/.auth/user.json";

// Logs in exactly once and persists the session. The tokens live in HttpOnly
// cookies (invisible to JS), but Playwright's storageState captures them from the
// browser context — so the other specs inherit the session without repeating the
// login flow on every test.
setup("authenticate", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#username").fill(DEMO_EMAIL);
  await page.locator("#password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  // A successful login redirects to the dashboard (root).
  await page.waitForURL("**/");
  await expect(page.getByText("DBaaS").first()).toBeVisible();

  await page.context().storageState({ path: AUTH_FILE });
});
