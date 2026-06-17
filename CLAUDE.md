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
- **Progress** — backend phases 0–8 complete; frontend F0–F7 complete (SQL Console shipped).
  Full phase detail and dependency map in [ROADMAP.md](ROADMAP.md).

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
```

## Conventions

**Backend (Python)**
- Use SQLAlchemy sync `Session` only — never `AsyncSession`.
- Pydantic v2: `model_validate`; `model_dump(exclude_unset=True)` for PATCH.
- Preserve the layer order — Routers → Services → Provisioners.
- Comment only when the *why* is non-obvious (a constraint or workaround).

**Frontend (TypeScript)** — App Router; small, single-responsibility components.

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
