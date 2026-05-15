# DBaaS Platform — Claude Code Instructions

> Central guidance document for AI agents (Claude Code) in this project.
> Update whenever conventions, stack, or roadmap changes.

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
> Files excluded from git (`.gitignore`) — `guide.md`, `scripts/`,
> `data/`, `.env` — may contain this information. **Files tracked by git**
> (source code, `requirements.txt`, `README.md`, `.env.example`) must contain
> **only generic and reusable values**.

---

## Commands

```bash
# Start environment
sudo docker compose up -d
source .venv/bin/activate
uvicorn src.main:app --reload --port 8001   # run from backend/

# Stop environment
kill $(lsof -t -i :8001)
sudo docker compose down

# Backend checks
cd backend
ruff check src/                             # lint
pytest                                      # tests (PHASE 10)
alembic upgrade head                        # apply migrations
alembic revision --autogenerate -m "desc"   # new migration

# Frontend
cd frontend
npm run dev                                 # dev server at localhost:3000
npm run build                               # production build
```

---

## 1. Project Context

**DBaaS Platform** — PostgreSQL database management platform focused on
**provisioning, monitoring, automating, and making databases unbreakable**.

DBA-as-a-Service for SMBs — a solo operator tool to manage multiple client
databases with monitoring, backup, automated maintenance, and proactive alerts.
Single-operator: no multi-user or multi-tenant system needed for now.
Public repository (portfolio for recruiters) — only generic, reusable
architecture is committed.

**Pillars:** Monitoring · Backup & Recovery · Automated Maintenance · Proactive Alerts

**Current status:** Phases 0–8 complete (backend). Frontend F0 in progress.
See [ROADMAP.md](ROADMAP.md) for full phase detail and dependency map.

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

| Layer      | Technology                                                  |
|------------|-------------------------------------------------------------|
| Backend    | FastAPI 0.115.0 (Python 3.12)                               |
| ORM        | SQLAlchemy 2.0.44 — **SYNC always** (Session + psycopg)    |
| Migrations | Alembic 1.17.2 — always run from `backend/`                |
| Database   | PostgreSQL 16 Alpine                                        |
| DB Admin   | pgAdmin                                                     |
| Frontend   | Next.js 15 (TypeScript, App Router, Tailwind, shadcn/ui)   |
| Environment | WSL2 Ubuntu 24.04, venv in `.venv/` (project root)        |

---

## 3. Code Conventions

**Python / Backend:**
- SQLAlchemy: sync Session only — never AsyncSession
- Pydantic v2: `model_validate`, `model_dump(exclude_unset=True)` for PATCH
- Routers call Services; Services call Provisioners — never skip layers
- No comments unless the WHY is non-obvious (hidden constraint, workaround)
- Commit convention: `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`

**TypeScript / Frontend:**
- Comments are mandatory during learning phase (exception to the no-comment rule)
- Each new file introduces exactly one new concept from the JS/TS/React/Next.js ecosystem

---

## 4. Response Instructions

1. **Context first** — Check current project state before any action.
2. **Chronological order** — what changes → why → how. No skips.
3. **Detailed explanations** — explain what, why, and how each concept relates.
   Include: file roles, import flow, new concepts in plain language.
4. **Objective and precise** — advance the project without creating rework.
5. **Error awareness** — check [.claude/error-history.md](.claude/error-history.md)
   before proposing solutions to avoid repeating past failures.
6. **Separate commits** — each major change = one commit (always in English).
7. **Complete code** — never partial, never `...` or `# rest of the code`.

### 4.1 Frontend-Specific Instructions

> ⚠️ **LEARNING CONTEXT — MANDATORY**
>
> The developer has **first contact** with JavaScript and its ecosystem (TypeScript,
> Node.js, React, Next.js). Starting a full-stack postgraduate program.
> The frontend is simultaneously product and classroom.

1. **Never create/edit files automatically** — send code in chat with explanations.
   Only create/edit files when the user explicitly asks ("create the file", "implement this").
2. **Each file = one lesson** — every new file introduces one new concept.
   Examples: `api.ts` → fetch/async-await; `AuthContext.tsx` → Context API;
   `middleware.ts` → Next.js route interception.
3. **Mandatory explanation before code:** what the concept is · why it exists ·
   how it works · how it connects to what was already built.
4. **Code annotations** — comments on every non-obvious block (learning exception).
5. **Backend analogies** — connect each concept to FastAPI/Python equivalents.
   `AuthContext` ↔ `get_current_user`; `middleware.ts` ↔ FastAPI middleware;
   `types.ts` ↔ Pydantic schemas.

### 4.2 Standard Response Format

Each implementation must follow this template:

```
### [Title of what is being created]

**What changes:** short description
**Why it changes:** technical justification

**File:** `relative/path/to/file.ext` (create new | edit existing)

\`\`\`language
[complete file code — never partial, never with "..." or "# rest of the code"]
\`\`\`

> If editing an existing file: indicate exactly WHERE to insert/change
> with context lines before and after.

**Commit:**
\`\`\`bash
git add path/to/file.ext
git commit -m "type: objective description of the change"
\`\`\`
```

**Rules:**
- Code always **complete** — the user does direct copy-paste
- Indicate **exact file path** relative to the project root
- If the file is new, say "create new"; if it exists, say "edit existing"
- Always close with the **commit command** with a descriptive message
- Commit convention: `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`
