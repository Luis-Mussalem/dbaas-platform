# Database as a Service Platform

Full-stack platform for provisioning, managing, monitoring, and maintaining PostgreSQL database instances. Combines a FastAPI backend with a Next.js frontend for end-to-end database lifecycle management.

This DBaaS was designed as a long-term engineering project focused on infrastructure automation, database lifecycle management, observability, security hardening, and operational reliability.

The project simulates real-world DBaaS concepts commonly found in modern platform engineering and cloud database services.

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)

[![CI](https://github.com/Luis-Mussalem/dbaas-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Luis-Mussalem/dbaas-platform/actions/workflows/ci.yml)
![Tests](https://img.shields.io/badge/tests-271%20passing-brightgreen?style=flat-square)
![Coverage](https://img.shields.io/badge/coverage-84%25-brightgreen?style=flat-square)
![Ruff](https://img.shields.io/badge/lint-ruff-blue?style=flat-square)

![JWT Authentication](https://img.shields.io/badge/Auth-JWT-black?style=flat-square)
![PITR](https://img.shields.io/badge/PostgreSQL-PITR-blue?style=flat-square)
![Observability](https://img.shields.io/badge/Observability-pg__stat__views-purple?style=flat-square)
![Architecture](https://img.shields.io/badge/Architecture-Modular-green?style=flat-square)

---

> **Note**
>
> This public repository contains a sanitized and simplified version of the platform.
>
> Sensitive infrastructure details, production credentials, operational environments, and client-specific configurations were intentionally excluded for security reasons.
>
> The repository preserves the core architecture, engineering concepts, and implementation patterns of the platform for portfolio purposes.

---

# Overview

Modern applications increasingly depend on scalable and automated infrastructure services.

This project explores how database infrastructure can be abstracted into a full-stack platform capable of:

- Provisioning PostgreSQL instances dynamically
- Managing database lifecycle and state transitions
- Monitoring health and performance metrics
- Performing automated maintenance routines
- Handling backups and recovery workflows
- Applying practical security hardening techniques
- Structuring infrastructure operations through APIs
- Exposing all of the above through a modern web interface

The goal is not only to build APIs, but to design systems that simulate operational challenges found in real backend and infrastructure environments.

---

# Screenshots

> The dashboard is a Next.js 16 App Router frontend (TypeScript, Tailwind v4).
> All data shown is real — provisioned PostgreSQL containers with seeded datasets.

| | |
|---|---|
| ![Fleet dashboard](docs/images/dashboard.png) **Fleet dashboard** — real-time KPIs (queries/s, P95 latency, 30-day uptime), region map and per-instance health. | ![Instance detail](docs/images/instance-detail.png) **Instance detail** — live metrics, connections, schema and slow queries per instance. |
| ![SQL console](docs/images/sql-console.png) **SQL console** — read-only SELECT runner with schema browser, results grid and `EXPLAIN` plans. | ![Replication](docs/images/replication.png) **Replication & HA** — streaming standbys with live lag and one-click promotion (failover). |
| ![Container logs](docs/images/logs.png) **Container logs** — live PostgreSQL stdout/stderr per instance. | ![Multi-tenant RBAC](docs/images/admin-users.png) **Multi-tenancy** — company workspaces, employee management and the capability/permission matrix. |

---

# Core Engineering Concepts

This project focuses heavily on backend engineering and operational concepts, including:

- Modular backend architecture
- Infrastructure abstraction layers
- Stateful resource management
- Database provisioning workflows
- Security hardening and defense-in-depth
- PostgreSQL observability
- Automated maintenance operations
- Backup and recovery strategies
- API-first platform design
- Reproducible containerized environments
- Full-stack integration with a typed React frontend

---

# Tech Stack

## Backend
- Python 3.12
- FastAPI 0.115

## Database
- PostgreSQL 16
- SQLAlchemy 2.0 (sync)
- Alembic
- psycopg

## Infrastructure
- Docker
- Docker SDK for Python

## Security
- JWT Authentication
- bcrypt
- cryptography (Fernet encryption)
- SlowAPI (rate limiting)

## Validation & Configuration
- Pydantic v2
- pydantic-settings
- python-dotenv

## Scheduling & Automation
- croniter

## Frontend
- Next.js 16 (App Router)
- TypeScript
- React 19
- Tailwind CSS v4
- shadcn/ui + Base UI
- recharts (metrics visualization)
- lucide-react (icons)

---

# Features

## Authentication & Security
- JWT access and refresh tokens
- Token revocation (blacklist)
- Timing-safe authentication flow
- Strong password validation
- Rate limiting on authentication endpoints
- Security headers middleware
- Restricted registration flow
- Encrypted connection URIs using Fernet

---

## Database Instance Management
- PostgreSQL instance provisioning via API
- Stateful lifecycle management
- Status transition validation
- Resource isolation
- CPU and memory limits
- Soft delete strategy

---

## Provisioning Engine
- Abstract provisioning interface
- Docker-based PostgreSQL provisioning
- Dedicated database roles per instance
- Secure connection string generation
- Health polling and status verification
- Self-healing across Docker restarts (`unless-stopped` containers + automatic reconciliation of instance status on startup)

---

## Monitoring & Observability
- PostgreSQL statistics collectors (`pg_stat_*`)
- Health checks per instance
- Query performance monitoring
- Slow query analysis
- Lock monitoring and deadlock inspection
- Index usage analysis
- Table bloat estimation
- `EXPLAIN ANALYZE` capture workflows
- Metrics retention policies
- Fleet KPIs on the dashboard — throughput (transactions/s), P95 query latency
  (`pg_stat_statements`), and 30-day uptime derived from a status-history table

---

## Backup & Recovery
- Logical backups (`pg_dump`)
- Physical backups (`pg_basebackup`)
- WAL archiving
- Point-in-Time Recovery (PITR)
- Scheduled backups
- Automatic retention cleanup
- Restore workflows

---

## Automated Operations
- Maintenance schedulers
- Metrics polling
- Backup scheduling
- Expired token cleanup
- Health monitoring tasks

---

## Alerts & Notifications
- Configurable alert rules per instance (threshold, condition, severity)
- Automated evaluation against collected metrics (60-second cycle)
- Auto-fire and auto-resolution of alert events
- Severity levels: info, warning, critical
- Default rule seed (connections, cache hit ratio, disk usage, long queries, backup age)
- HTTP webhook integration for external notification delivery

---

## Replication & High Availability
- Streaming physical replicas provisioned from a primary via `pg_basebackup` (`-R`, hot standby)
- Each standby joins the fleet as a first-class instance (own status, port, metrics)
- Continuous lag monitoring on the primary (`pg_stat_replication`) — bytes and seconds behind, refreshed every 30 s
- Manual failover: promote a standby to standalone primary (`pg_promote`) via `POST /replicas/{id}/promote`
- Company-scoped like every other resource (a replica of another company's instance is a 404)

---

## Administration & Audit
- Platform dashboard with consolidated health view across all instances
- Audit log with automatic event capture via middleware (no manual annotation)
- 11 audited action types across auth, instances, backups, and maintenance
- Filterable audit trail by action type, resource type, and user

---

## Multi-Tenancy
- Company model with per-company resource scoping — regular users see only their company's instances
- Superuser active-company switcher: `WorkspaceSwitcher` writes the selected company to `X-Company-Id` header, backend filters accordingly
- All derived resources (backups, alerts, metrics, maintenance) inherit scoping via the instance choke-point
- Employee management — company-scoped user CRUD (create, edit, deactivate)
- Company-admin RBAC: two orthogonal axes — platform `is_superuser` × intra-company `admin`/`member` role; company admins manage their own company, with a guard against removing the last active admin
- Per-company audit scoping — each company sees only its own audit trail
- Superuser bypasses the filter and sees all companies simultaneously

---

## Frontend Interface
- JWT authentication with token rotation (login, logout, protected routes)
- Instance list with status badges and resource summary
- Instance detail with tabbed views (overview, metrics, backups, maintenance, alerts, replication, logs)
- Start / Stop / Delete actions with reactive status updates
- Time-series metric charts (cache hit ratio, connections) with 15m/1h/6h/24h window selector
- Live monitoring: slow queries and active locks
- Backups management — list, create, restore and scheduling
- Maintenance actions and alert rules/events management
- Replication tab — create standbys, watch live lag, promote to primary
- Container logs viewer — live PostgreSQL stdout/stderr per instance
- SQL console — read-only query runner with schema browser, results grid and `EXPLAIN` plans
- Consolidated dashboard and audit log
- Workspace switcher — active-company selection propagated to every API call
- Redesigned dark UI: collapsible sidebar, world-map region picker, light/dark themes

---

# Architecture

The project is organized as a monorepo separating backend, frontend, and data layers.

```text
dbaas-platform/
│
├── backend/                  # Python / FastAPI
│   ├── src/
│   │   ├── collectors/       # PostgreSQL metrics & statistics collectors
│   │   ├── core/             # Configuration, security, database setup
│   │   ├── models/           # SQLAlchemy ORM models
│   │   ├── routers/          # API routes/endpoints
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── services/         # Business logic and workflows
│   │   └── main.py           # FastAPI application entrypoint
│   ├── alembic/              # Database migrations
│   └── requirements.txt
│
├── frontend/                 # Next.js (TypeScript, App Router)
│   ├── app/
│   │   ├── layout.tsx        # Root layout with global auth provider
│   │   ├── page.tsx          # Instance list dashboard
│   │   ├── login/            # Login page
│   │   └── instances/[id]/   # Instance detail (dynamic route)
│   ├── components/           # Reusable UI components
│   ├── context/              # React Context (auth state)
│   ├── hooks/                # Custom hooks (instances, metrics)
│   ├── lib/                  # API client, types, utilities
│   └── middleware.ts         # Route protection (Next.js middleware)
│
├── data/                     # Runtime backups and WAL archives (gitignored)
│
├── docker-compose.yaml       # PostgreSQL + pgAdmin
└── .env.example              # Environment variable template
```

---

# Service-Oriented Design

The platform separates responsibilities into distinct layers:

| Layer | Responsibility |
|---|---|
| Routers | Request handling and API exposure |
| Schemas | Data validation and serialization |
| Services | Business rules and workflows |
| Models | Persistence layer |
| Collectors | Metrics and observability |
| Core | Infrastructure and security |

This separation allows the project to evolve without tightly coupling infrastructure logic to HTTP endpoints.

---

# Provisioning Workflow

The provisioning flow follows a multi-step orchestration process:

```text
API Request
    ↓
Router
    ↓
Service Layer
    ↓
Provisioner Interface
    ↓
Docker Provisioner
    ↓
PostgreSQL Container
    ↓
Health Polling & Status Update
```

Each database instance behaves as a managed infrastructure resource with its own lifecycle and operational state.

---

# Security Approach

Security was treated as a first-class concern throughout the project.

The platform applies a defense-in-depth strategy combining multiple layers of protection:

- JWT validation
- Token revocation
- Rate limiting
- Strong password policies
- Encrypted connection strings
- Security headers
- Restricted registration flow
- Timing-safe authentication
- Docker networking restrictions
- CORS hardening

The objective is to simulate realistic backend security practices beyond basic authentication flows.

---

# Observability

The monitoring layer goes beyond superficial health checks.

The platform interacts directly with PostgreSQL internal statistics views to inspect database behavior in depth.

Examples include:

- Active connections
- Transaction throughput
- Cache hit ratio
- Lock analysis
- Slow queries
- Query execution plans
- Index usage efficiency
- Table/index bloat estimation

This allows the platform to simulate operational monitoring scenarios commonly found in production database environments.

---

# Backup & Recovery Strategy

The platform implements two complementary backup approaches.

## Logical Backups

Using:
- `pg_dump`
- `pg_restore`

Focused on:
- Portability
- Selective restores
- Version compatibility

---

## Physical Backups & PITR

Using:
- WAL archiving
- Physical backup workflows

Focused on:
- Disaster recovery
- Point-in-Time Recovery
- Continuous recovery workflows

This mirrors backup strategies used in real PostgreSQL production environments.

---

# Testing & Quality Assurance

Quality is enforced automatically on every push and pull request.

## Automated Test Suite
- **271 tests** with **84% backend coverage** (`pytest` + `pytest-cov`)
- Isolated PostgreSQL test database (`dbaas_test`, created by the test suite) —
  never touches development data
- External dependencies are faked, not invoked: Docker SDK, `subprocess`
  (`pg_dump` / `pg_restore` / `pg_basebackup`) and live `psycopg` connections
  are mocked, so the suite runs **without Docker and without any managed
  (client) database** — only a local PostgreSQL for the metadata test DB
- Coverage spans the business-critical layers: instance state machine, alert
  evaluation engine, backup orchestration, maintenance executors, the
  provisioner, and all background pollers/schedulers

## Continuous Integration
GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs three jobs in parallel:

| Job | What it does |
|---|---|
| **Backend** | `ruff` lint + `pytest` against a PostgreSQL 16 service container |
| **Frontend** | `eslint` + `tsc --noEmit` + `next build` |
| **Docker** | Builds the multi-stage backend image (validates the Dockerfile) |

## Containerization
- Multi-stage [`Dockerfile`](backend/Dockerfile): isolated build stage, lean runtime
- Runs as a **non-root** user (defense in depth)
- Ships `postgresql-client-16` so backup/restore work in-container
- Base pinned to `python:3.12-slim-bookworm` for reproducible builds

---

# Engineering Challenges & Lessons Learned

Throughout development, several operational and architectural issues were intentionally documented and resolved.

Examples include:

- Authentication edge cases
- Bcrypt compatibility issues
- Environment variable parsing failures
- Query sanitization vulnerabilities
- Metrics retention growth problems
- Token lifecycle cleanup
- URL encoding edge cases
- Docker networking restrictions

The project maintains an internal engineering log documenting:
- root causes
- debugging process
- mitigation strategies
- architectural decisions

The goal is to reinforce operational thinking and long-term maintainability.

---

# Development Approach

This project follows an engineering-first and learning-oriented development workflow.

Claude Code assisted development tools were used primarily for:

- architecture planning
- technical research
- debugging support
- documentation refinement
- accelerated learning of backend, infrastructure, and frontend concepts

The focus remains on understanding system design decisions, PostgreSQL internals, backend engineering practices, and operational workflows rather than relying on autonomous code generation.

This approach was intentionally adopted to reinforce deep technical understanding while accelerating iteration and experimentation during development.

---

# Running the Project

## Clone the repository

```bash
git clone https://github.com/Luis-Mussalem/dbaas-platform.git
cd dbaas-platform
```

---

## Create environment variables

Create a `.env` file based on the provided `.env.example`:

```bash
cp .env.example .env
```

The example file already contains all required configuration variables for:

- PostgreSQL
- JWT authentication
- Encryption keys
- Docker provisioning
- pgAdmin
- CORS configuration

---

## Option A — Full stack with Docker Compose

Builds and runs everything (PostgreSQL + pgAdmin + backend API + frontend):

```bash
docker compose up --build
```

- Frontend: `http://localhost:3000`
- API / Swagger: `http://localhost:8001/docs`

The backend runs in `network_mode: host` so the provisioner can reach the
sibling database containers it creates on the host loopback, and mounts the
Docker socket + the repo's `data/` directory (see the comments in
[`docker-compose.yaml`](docker-compose.yaml)). Run the command from the repo root.

---

## Option B — Run backend & frontend manually (development)

Start only the infrastructure, then run each app with hot reload:

```bash
docker compose up -d postgres pgadmin

# API (from backend/, with the virtualenv active)
source .venv/bin/activate
cd backend
uvicorn src.main:app --reload --port 8001

# Frontend (from frontend/)
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:3000`.

---

## Access the API

Swagger UI:

```
http://localhost:8001/docs
```

ReDoc:

```
http://localhost:8001/redoc
```

Health check:

```
http://localhost:8001/health
```

---

## Run the tests

```bash
cd backend
pip install -r requirements-dev.txt
ruff check src/ tests/      # lint
pytest --cov=src            # tests + coverage
```

The suite runs against an isolated `dbaas_test` database and requires no Docker.

---

## Build the backend image

```bash
docker build -t dbaas-backend backend/
```

---

# Current Development Status

## Backend — Complete

- Foundation & project structure
- Authentication (JWT, token rotation, revocation)
- Security hardening
- Database instance modeling
- Provisioning engine (Docker-based)
- Monitoring & observability
- Backup & PITR
- Infrastructure scaling groundwork
- Automated maintenance workflows
- Alerting & notifications system
- Administration panel & audit log
- Multi-tenancy (companies, per-company scoping, employee management, company-admin RBAC, audit scoping)
- Streaming replication & high availability (standbys, lag monitoring, manual failover)
- Per-instance container logs endpoint
- Automated testing (271 tests, 84% coverage)
- Continuous integration & full-stack Docker Compose (multi-stage backend + frontend images)

## Frontend — Complete

| Feature | Status |
|---|---|
| Authentication (login, logout, token rotation, protected routes) | ✅ Complete |
| Instance list with status badges | ✅ Complete |
| Instance detail page (dynamic routing) | ✅ Complete |
| Start / Stop / Delete actions | ✅ Complete |
| Slow queries & locks visualization | ✅ Complete |
| Backups management (list, create, restore, schedule) | ✅ Complete |
| Maintenance & alerts interface | ✅ Complete |
| Consolidated dashboard + audit log | ✅ Complete |
| Time-series metric charts (cache hit ratio, connections) | ✅ Complete |
| SQL console (read-only SELECT, schema browser, EXPLAIN, history) | ✅ Complete |
| Replication tab (create standby, live lag, promote) | ✅ Complete |
| Container logs viewer | ✅ Complete |

## Planned Future Phases

- Cloud deployment (managed hosting, TLS, domain)
- Observability stack integration (Prometheus / Grafana)

---

# Future Improvements

Potential future improvements include:

- Real-time monitoring dashboards
- Container orchestration
- Distributed task queues
- Cloud-native deployment
- Observability stack integration (Prometheus / Grafana)

---

# Why This Project Matters

This project was designed to go beyond a traditional CRUD backend application.

The project focuses on:
- backend engineering
- infrastructure workflows
- operational reliability
- observability
- lifecycle management
- security hardening
- PostgreSQL internals
- full-stack product development

It represents an effort to bridge backend development, infrastructure-oriented system design, and modern frontend engineering through a product-oriented approach.

---

# Author

Luis Mussalem

- LinkedIn: https://www.linkedin.com/in/luis-mussalem
- GitHub: https://github.com/Luis-Mussalem
