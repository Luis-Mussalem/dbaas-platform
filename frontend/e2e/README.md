# End-to-end tests (Playwright)

Smoke tests over the critical path — the flows a recruiter actually clicks
through: **login → dashboard → navigation → command palette → instance detail.**
They are read-only (no create/delete), so they are safe to run against the demo
stack.

## What's covered

| Spec | Checks |
|---|---|
| `login.spec.ts` | Form renders · rejects invalid credentials · signs in and reaches the dashboard |
| `dashboard.spec.ts` | Dashboard loads with the seeded fleet |
| `navigation.spec.ts` | Sidebar navigation · **⌘K/Ctrl+K command palette** opens, navigates, closes |
| `instances.spec.ts` | Instances list renders and opens an instance detail |

`auth.setup.ts` logs in once and saves the session (`e2e/.auth/user.json`); the
other specs reuse it, so login isn't repeated per test. Auth lives in **HttpOnly
cookies** — Playwright's `storageState` captures them from the browser context.

## Prerequisites

The full stack must be running (the tests hit the **real backend** to authenticate):

```bash
sudo docker compose up -d          # frontend :3000 + backend :8001 + postgres
```

Credentials default to the demo account (`dev-test@local.dev` / `dev-test-2026`);
override with `E2E_EMAIL` / `E2E_PASSWORD`, and the target with `E2E_BASE_URL`.

## Running

**Locally** (needs the browser + its system libraries once):

```bash
cd frontend
npx playwright install --with-deps chromium   # first time only
npm run test:e2e                              # headless
npm run test:e2e:ui                           # interactive UI mode
```

**Via the official Playwright image** (no host libraries needed — the approach
used to validate these tests):

```bash
cd frontend
docker run --rm --network host -v "$PWD":/work -w /work \
  mcr.microsoft.com/playwright:v1.61.1-noble npx playwright test
```
