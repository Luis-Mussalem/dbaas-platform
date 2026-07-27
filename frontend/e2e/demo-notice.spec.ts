import { test, expect } from "@playwright/test";

// The fleet is generated on purpose, and that has to be CLEAR on screen: a persistent
// banner across the dashboard + an "About this demo" page with the full
// explanation. The "Simulate usage" reel was removed — these tests pin down that contract.

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
  // The journey of the removed button is part of the on-screen documentation.
  await expect(page.getByText(/simulate usage/i)).toBeVisible();
});

test("the removed simulation endpoints are gone", async ({ page }) => {
  const res = await page.request
    .get("/api/v1/demo/simulation")
    .catch(() => null);
  // 404 (route removed) — never 200.
  if (res) expect(res.status()).toBe(404);
});
