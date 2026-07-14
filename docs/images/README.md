# Screenshots

Drop the captured PNGs here with these exact names (referenced by the root `README.md`):

| File | Screen | How to reach it |
|------|--------|-----------------|
| `dashboard.png` | Fleet dashboard (Painel) | `/` — the KPI row + region map + instance cards |
| `instance-vision.png` | Instance overview, "Visão geral" tab | `/instances/{id}` — stat cards, connections, schema explorer, slow queries |
| `instance-detail.png` | Instance metrics, "Métricas" tab | `/instances/{id}` → "Métricas" — pick a window (1h/6h) with a populated curve |
| `sql-console.png` | SQL console | `/sql` — run a `SELECT` so the results grid is populated |
| `logs.png` | Container logs tab | `/instances/{id}` → "Logs" |
| `admin-users.png` | Employees / RBAC matrix | `/admin/users` (log in as the superuser) |

> `logs.png` is **not currently referenced by the root README**: the captured file
> predates the WAL-archive fix and shows the `Permission denied` wall that the
> README's case study describes as resolved. Re-link it once recaptured.

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
