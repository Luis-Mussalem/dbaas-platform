import { test, expect } from "@playwright/test";
import { DEMO_EMAIL, DEMO_PASSWORD } from "./helpers";

// These tests exercise the login screen itself, so they run WITHOUT the saved
// session (anonymous context overriding the project's storageState).
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

  // Stays on the login screen and shows an error — doesn't navigate to the dashboard.
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
