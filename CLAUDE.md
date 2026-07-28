# DBaaS Platform

PostgreSQL **DBA-as-a-Service** for SMB fleets — provisioning, monitoring, backup &
recovery, automated maintenance, and proactive alerting, delivered through a FastAPI
backend and a Next.js dashboard.

> Public portfolio repository. Only generic, reusable architecture is committed —
> see **Security & privacy** below.

## Overview

The platform manages multiple client PostgreSQL databases and is evolving toward
**multi-tenancy**: many companies, each with its own employees. A regular user sees
only their own company; the admin superuser sees and switches between all.

- **Multi-tenant status** — PHASE 11 complete (Stages A–E): instances and their derived
  resources are filtered by `company_id`; the superuser's active company is selected via
  the `WorkspaceSwitcher` and propagated as an `X-Company-Id` header; employee management,
  company-admin RBAC (`is_superuser` × `admin`/`member`), and per-company audit scoping
  are all in place.
- **Authorization — two rules, both load-bearing.** Read `backend/src/core/scoping.py`
  and `get_current_company_admin` before touching any endpoint.
  1. **Scope (which rows):** `company_scope(user)` returns a `CompanyScope` with THREE
     cases — unrestricted (superuser, no workspace), one company, or *empty* (a regular
     user with no company sees **nothing**). Never reduce a read filter to a bare
     `Optional[UUID]`: `None` would mean both "everything" and "nothing".
     `visible_company_id()` survives only for assigning `company_id` to a row being
     created — never for building a read filter.
  2. **Gate (read or write):** **members observe, admins operate.** A new endpoint that
     MUTATES takes `current_user: User = Depends(get_current_company_admin)`; a
     read-only one takes `get_current_user`. `tests/test_write_permissions.py` walks
     every mutating route, so a missing dependency shows up as a failed test.
  The frontend mirrors the gate with `useCanManage()` purely to decide what to render —
  it is not enforcement, and the backend must never depend on it.
- **Progress** — ROADMAP 100% complete: backend phases 0–10 and frontend F0–F8 all
  shipped. Phase 9 (streaming replication & HA — standbys via `pg_basebackup -R`, lag
  monitoring, manual failover) and Phase 10 (container logs, full-stack docker-compose,
  frontend CI, OpenAPI tags) landed 2026-07-07. A visual-polish pass (2026-07-02) added
  real fleet KPIs (queries/s, P95 latency, 30-day uptime via `instance_status_history`),
  per-user last-activity, and a dashboard/instances/employees redesign. Fleet cards
  (2026-07-21) show operational state instead of flat gauges — throughput, P95, storage
  used/plan with 24h growth, open alerts, last backup and 30-day uptime — all from one
  `GET /instances/fleet-summary` (`services/fleet_summary.py`). An **always-live demo
  fleet** (2026-07-22) replaced the earlier *Simulate usage* reel: instead of an empty
  boot + an on-demand ~90s scripted director, the seed now enriches the fleet on boot
  (`seed/demo._enrich_boot` → 24h metrics, uptime, backups, alerts, maintenance) and a
  continuous **baseline load** (`services/workload_simulator.py`, `BASELINE_INTENSITY`)
  keeps it alive, with per-instance ballast for a believable storage spread (~37–61%
  prod / ~14–29% staging). The demo is transparent on screen — a persistent `DemoNotice`
  banner + an *About this demo* page at `/demo` — and gated by `DEMO_MODE` / the
  build-time `NEXT_PUBLIC_DEMO_MODE`. The reel director, its `demo_simulation` table and
  the `/demo/simulation/*` endpoints were removed. Full phase detail and dependency map
  in [ROADMAP.md](ROADMAP.md).
- **i18n** — the UI is bilingual (EN default, PT via the top-bar toggle), using next-intl
  with the locale in a `NEXT_LOCALE` cookie (no `/[locale]/` in the URLs). ~460 keys in
  `messages/{en,pt}.json`; parity is enforced in CI by `npm run i18n:check`. Everything
  outside the UI — README, code, API errors, OpenAPI docs — is English only.

## Architecture

```
dbaas-platform/
├── backend/    Python / FastAPI — src/ (models, schemas, routers, services, core), alembic/
├── frontend/   Next.js 16 — App Router, TypeScript, Tailwind, shadcn/ui
├── data/       Runtime backups (gitignored — only structure tracked)
└── docker-compose.yaml
```

Requests flow through strict layers — **Routers → Services → Provisioners** — and never
skip a layer. All database access uses SQLAlchemy **sync** sessions (never `AsyncSession`).

## Stack

| Layer       | Technology                                              |
|-------------|---------------------------------------------------------|
| Backend     | FastAPI 0.115 (Python 3.12)                             |
| ORM         | SQLAlchemy 2.0 — sync `Session` + `psycopg`             |
| Migrations  | Alembic 1.17 — run from `backend/`                      |
| Database    | PostgreSQL 16 Alpine                                     |
| Frontend    | Next.js 16 — App Router, TypeScript, React 19, Tailwind v4, shadcn/ui|
| Tooling     | Ruff (lint), Pytest (tests), Docker Compose             |

## Commands

```bash
# Run
sudo docker compose up -d
source .venv/bin/activate
uvicorn src.main:app --reload --port 8001        # from backend/

# Backend checks (from backend/)
ruff check src/                                   # lint
pytest                                            # tests
alembic upgrade head                              # apply migrations
alembic revision --autogenerate -m "message"      # new migration

# Frontend (from frontend/)
npm run dev                                        # http://localhost:3000
npm run build
npm run i18n:check                                 # en/pt message parity (runs in CI)
```

## Conventions

**Backend (Python)**
- Use SQLAlchemy sync `Session` only — never `AsyncSession`.
- Pydantic v2: `model_validate`; `model_dump(exclude_unset=True)` for PATCH. For a
  field where explicit `null` is meaningful (e.g. `retention_days` = keep forever),
  read presence from `model_fields_set`, not from `is not None`.
- Preserve the layer order — Routers → Services → Provisioners.
- Apply the two authorization rules above to every new endpoint.
- Anything written to a column the API returns must be safe to return. Subprocess and
  psycopg errors go through `core.redaction.redact_error` before being persisted; the
  unredacted text goes to the log.
- Comment only when the *why* is non-obvious (a constraint or workaround).

**Frontend (TypeScript)** — App Router; small, single-responsibility components.
- **No hardcoded UI strings.** Every user-visible string lives in `messages/{en,pt}.json`;
  `en.json` is the source of the types. Add keys alphabetically to *both* files.
- `t` is always the translator (`tc` for `Common`) — never shadow it with a `map` variable.
- Never concatenate translated fragments: use one ICU `select`/`plural` with the full
  sentence per branch.

**Commits** — Conventional prefixes (`feat:`, `fix:`, `chore:`, `refactor:`, `docs:`), in English.

## Security & privacy (public repo)

- **Never commit secrets** — passwords, `JWT_SECRET_KEY`, API tokens, real connection
  strings, or any real `.env`. `.env` is gitignored; `.env.example` documents variable
  names with placeholder values only.
- Committed files must hold **only generic, reusable values** — no client data and
  nothing that identifies a client.
- Private/local files stay gitignored: `guide.md`, `scripts/`, `data/`, `.env`,
  `AGENTS.md`, `CLAUDE_dev.md`, `dev_doc/`.
- Before `git add`, review the staged diff: `git diff --staged`.

---
