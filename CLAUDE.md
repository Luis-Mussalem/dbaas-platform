# DBaaS Platform — Engineering & AI Pair-Programming Guide

> Guidance for AI agents (Claude Code) working in this repository, and a public
> overview of how the project is built. Keep this file focused — it loads every session.

## Development Approach — AI-Assisted Engineering

This codebase is built through structured **pair-programming with Claude Code**,
used deliberately as a vehicle to practice and master backend and full-stack
engineering. The emphasis is on disciplined fundamentals over speed:

- A strict **layered architecture** — Routers → Services → Provisioners, never skipping layers.
- **Migration hygiene** — every schema change goes through Alembic.
- **Security & privacy by default** — see the rules below.
- **Consistent conventions** so the codebase stays legible and reviewable.

Local-only development guidance (workflow, command reference, detailed working
agreements) is kept out of this public repository — see the note at the end.

> ⚠️ **SECURITY RULE — NEVER IGNORE**
>
> The following must **never go to GitHub** under any circumstances:
> - Passwords (database, pgAdmin, external APIs)
> - JWT secret keys (`JWT_SECRET_KEY`)
> - API tokens (Stripe, AWS, SendGrid, etc.)
> - Connection strings with real credentials
> - Any `.env` file with real production or staging values
>
> The `.env` file is in `.gitignore` for exactly this reason.
> The `.env.example` exists to document **which variables exist**, with
> placeholder values only — never real values.
>
> Before any `git add`, verify: **no sensitive data is being committed.**
> When in doubt, use `git diff --staged` to review what is staged.

> ⚠️ **PRIVACY RULE — NEVER IGNORE**
>
> This repository is **public** (portfolio). Before creating or editing any file
> that goes to git, verify the content does not expose:
> - Credentials, secrets, or tokens in any form
> - Real client data or operational information
> - Any information identifying specific clients
>
> Files excluded from git (`.gitignore`) — `guide.md`, `scripts/`, `data/`,
> `.env`, `AGENTS.md`, `CLAUDE_dev.md`, `dev_doc/` — may contain private or
> work-in-progress notes. **Files tracked by git** (source code,
> `requirements.txt`, `README.md`, `.env.example`) must contain **only generic
> and reusable values**.

---

## 1. Project Context

**DBaaS Platform** — PostgreSQL management platform: provisioning, monitoring,
backup, automated maintenance, proactive alerts. DBA-as-a-Service for SMBs.
**Pillars:** Monitoring · Backup & Recovery · Automated Maintenance · Proactive Alerts.

**Multi-tenant (in progress):** multiple companies, each with its own employees.
A regular user sees only their own company; the **admin superuser** sees and
switches between all. **PHASE 11 Stage A (per-company resource scoping) is DONE** —
instances and their derived resources (via the `get_instance_or_404` choke-point)
and the admin dashboard are filtered by `company_id`; the superuser bypasses the
filter. **Remaining:** superuser active-company (Stage B), employee management,
RBAC, audit scoping. Full detail in [ROADMAP.md](ROADMAP.md) PHASE 11.

**Status:** Backend phases 0–8 complete; PHASE 11 Stage A done. Frontend F0–F6
(F3 metrics charts partial, F7 SQL console deferred).

Public repo (portfolio) — only generic, reusable architecture is committed.

---

## 2. Stack

```
dbaas-platform/
├── backend/          ← Python/FastAPI (src/, alembic/, alembic.ini, requirements.txt)
├── frontend/         ← Next.js 15 (TypeScript, App Router, Tailwind, shadcn/ui)
├── data/             ← Backups at runtime (gitignored — only structure tracked)
├── docker-compose.yaml
└── .env / .env.example
```

| Layer       | Technology                                              |
|-------------|---------------------------------------------------------|
| Backend     | FastAPI 0.115.0 (Python 3.12)                           |
| ORM         | SQLAlchemy 2.0.44 — **SYNC always** (Session + psycopg) |
| Migrations  | Alembic 1.17.2 — always run from `backend/`             |
| Database    | PostgreSQL 16 Alpine                                     |
| DB Admin    | pgAdmin                                                  |
| Frontend    | Next.js 15 (TypeScript, App Router, Tailwind, shadcn/ui)|
| Environment | WSL2 Ubuntu 24.04, venv in `.venv/` (project root)      |

---

## 3. Code Conventions

**Python / Backend:**
- SQLAlchemy: sync Session only — never AsyncSession
- Pydantic v2: `model_validate`, `model_dump(exclude_unset=True)` for PATCH
- Routers call Services; Services call Provisioners — never skip layers
- No comments unless the WHY is non-obvious (hidden constraint, workaround)

**TypeScript / Frontend:**
- TypeScript, App Router; one new concept introduced per new file
- Components favor clarity and explicit, well-commented logic

**Commit convention:** `feat:`, `fix:`, `chore:`, `refactor:`, `docs:` (always in English).

---

## 4. Response Principles

1. **Context first** — check current project state before any action.
2. **Chronological** — what changes → why → how. No skips.
3. **Explain as you go** — state *what, why, and how*, and relate frontend concepts
   to their FastAPI/Python analogues. Keep depth proportional to novelty.
4. **Complete code** — never partial, never `...` or `# rest of the code`.
5. **Error awareness** — check [.claude/error-history.md](.claude/error-history.md)
   before proposing fixes, to avoid repeating past failures.

---

