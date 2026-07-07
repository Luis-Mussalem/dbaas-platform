# Screenshots

Drop the captured PNGs here with these exact names (referenced by the root `README.md`):

| File | Screen | How to reach it |
|------|--------|-----------------|
| `dashboard.png` | Fleet dashboard (Painel) | `/` — the KPI row + region map + instance cards |
| `instance-detail.png` | Instance detail, "Visão geral" or "Métricas" tab | `/instances/{id}` |
| `sql-console.png` | SQL console | `/sql` — run a `SELECT` so the results grid is populated |
| `replication.png` | Replication tab | `/instances/{id}` → "Replicação" (create a replica first, so lag shows) |
| `logs.png` | Container logs tab | `/instances/{id}` → "Logs" |
| `admin-users.png` | Employees / RBAC matrix | `/admin/users` (log in as the superuser) |

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
