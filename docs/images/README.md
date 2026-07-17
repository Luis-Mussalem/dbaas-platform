# Screenshots

Drop the captured PNGs here with these exact names (referenced by the root `README.md`):

| File | Screen | How to reach it |
|------|--------|-----------------|
| `dashboard.png` | Fleet dashboard (hero, full-width) | `/` — KPI row + region map + instance cards + activity feed |
| `instances.png` | Instances list | `/instances` — the fleet cards with the environment filter |
| `instance-view.png` | Instance overview, "Overview" tab | `/instances/{id}` — stat tiles, connections, schema explorer, slow queries |
| `instance-detail.png` | Instance metrics, "Metrics" tab | `/instances/{id}` → "Metrics" — pick a window (1h/6h) with a populated curve |
| `sql-console.png` | SQL console | `/sql` — run a `SELECT` so the results grid is populated |
| `logs.png` | Logs & Audit trail | `/audit` — the filterable action log |
| `admin-users.png` | Employees / RBAC matrix | `/admin/users` (log in as the superuser) |

> Capture the UI in **English** (the language toggle is in the top bar) — the whole
> set must be consistent. The instance-metrics latency chart is labelled *demo* in
> the UI; that is expected (the backend collects fleet-wide P95, not per-execution).

> The Replication tab is intentionally **not** in the README: with no standby
> provisioned it renders empty, and a screenshot of an empty state undersells the
> feature. Replication is covered in the README's feature list instead.

> **Never screenshot `/docs` or `/redoc`.** Swagger's title comes from `APP_NAME`
> in your local `.env` (`backend/src/main.py`), which holds the real product name —
> it must not reach this public repo. The dashboard is safe: the sidebar brand is
> hardcoded as "DBaaS".

## Getting to a screenshot-ready state (real data)

```bash
docker compose up -d postgres pgadmin
source .venv/bin/activate
cd backend
# private, gitignored seed scripts:
python ../scripts/seed_demo_companies.py
python ../scripts/generate_seed_datasets.py
python ../scripts/seed_demo_instances.py     # provisions real containers with data
uvicorn src.main:app --reload --port 8001
# in another shell: cd frontend && npm run dev
```

Log in as the superuser and use the `WorkspaceSwitcher` to show the multi-tenant
angle. Capture at a consistent window width (≈1400px) for a uniform look.

> Tip: on WSL2, the Windows Snipping Tool (Win+Shift+S) captures the browser fine;
> save straight into this folder.
