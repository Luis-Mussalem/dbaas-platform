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
- **Progress** — ROADMAP 100% complete: backend phases 0–10 and frontend F0–F8 all
  shipped. Phase 9 (streaming replication & HA — standbys via `pg_basebackup -R`, lag
  monitoring, manual failover) and Phase 10 (container logs, full-stack docker-compose,
  frontend CI, OpenAPI tags) landed 2026-07-07. A visual-polish pass (2026-07-02) added
  real fleet KPIs (queries/s, P95 latency, 30-day uptime via `instance_status_history`),
  per-user last-activity, and a dashboard/instances/employees redesign. 272 tests, 82%
  backend coverage. Full phase detail and dependency map in [ROADMAP.md](ROADMAP.md).
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
- Pydantic v2: `model_validate`; `model_dump(exclude_unset=True)` for PATCH.
- Preserve the layer order — Routers → Services → Provisioners.
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
