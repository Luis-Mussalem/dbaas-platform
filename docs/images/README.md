# Screenshots

These PNGs are **generated**, not captured by hand — see
[Regenerating them](#regenerating-them) below. The names are referenced by the
root `README.md`:

| File | Screen | How to reach it |
|------|--------|-----------------|
| `dashboard.png` | Fleet dashboard (hero, full-width) | `/` — KPI row + region map + instance cards + activity feed |
| `instances.png` | Instances list | `/instances` — the fleet cards with the environment filter |
| `instance-view.png` | Instance overview, "Overview" tab | `/instances/{id}` — stat tiles, connections, schema explorer, slow queries |
| `instance-detail.png` | Instance metrics, "Metrics" tab | `/instances/{id}` → "Metrics" — pick a window (1h/6h) with a populated curve |
| `sql-console.png` | SQL console | `/sql` — run a `SELECT` so the results grid is populated |
| `logs.png` | Logs & Audit trail | `/audit` — the filterable action log |
| `admin-users.png` | Employees / RBAC matrix | `/admin/users` (log in as the superuser) |

> The set is captured in **English** (the script forces `NEXT_LOCALE=en`) so it stays
> consistent. The instance-metrics latency chart is labelled *demo* in the UI; that is
> expected (the backend collects fleet-wide P95, not per-execution).

> The Replication tab is intentionally **not** in the README: with no standby
> provisioned it renders empty, and a screenshot of an empty state undersells the
> feature. Replication is covered in the README's feature list instead.

> **Never screenshot `/docs` or `/redoc`.** Swagger's title comes from `APP_NAME`
> in your local `.env` (`backend/src/main.py`), which holds the real product name —
> it must not reach this public repo. The dashboard is safe: the sidebar brand is
> hardcoded as "DBaaS".

## Regenerating them

Bring the full stack up and let it run for a few minutes — the demo fleet seeds
itself on boot and the baseline workload fills the charts, so the cards have real
throughput and storage to show:

```bash
docker compose up -d
```

Then run the capture from `frontend/`, using the official Playwright image so no
browser libraries are needed on the host:

```bash
cd frontend
docker run --rm --network host -v "$PWD/..":/repo -w /repo/frontend \
  mcr.microsoft.com/playwright:v1.61.1-noble \
  npx playwright test --config=playwright.screenshots.config.ts
```

The script (`e2e/screenshots.ts`) logs in as the demo superuser, walks the seven
screens and writes the PNGs straight into this folder at 1860×930 @2x. It is kept
out of the smoke suite — `playwright.config.ts` ignores it — because it writes to
the repository. Point it somewhere else first if you want to review before
overwriting:

```bash
docker run --rm --network host -v "$PWD/..":/repo -v /tmp/shots:/shots \
  -w /repo/frontend -e SHOTS_OUT=/shots \
  mcr.microsoft.com/playwright:v1.61.1-noble \
  npx playwright test --config=playwright.screenshots.config.ts
```

> A cold boot fails the first scheduled backup on every instance (the containers
> are still starting), which shows up on the cards as a failed backup. Either wait
> for the next scheduled run or trigger one manually before capturing.
