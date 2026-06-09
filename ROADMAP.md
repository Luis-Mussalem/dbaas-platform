# DBaaS Platform — Project Roadmap

> Roadmap oriented to the central objective: mastering database engineering.
> Each phase delivers a real database management capability.
> Phases are sequential — each depends on the previous ones.

## PHASE 0 — Foundation `[x]`

> Project skeleton. Everything is built on this.

| Deliverable | Description |
|-------------|-------------|
| Folder structure | `backend/src/` with package layout (models, schemas, routers, services, core) |
| Docker Compose | PostgreSQL 16 Alpine + pgAdmin — complete local environment |
| Configuration | `.env.example` + `pydantic-settings` to manage variables |
| FastAPI app | Application initialized with CORS and standardized exception handling |
| SQLAlchemy | Sync engine + `SessionLocal` factory with `psycopg` |
| Alembic | Initialized, configured to read URL from `.env` |
| Health check | `GET /health` returns API status and database connectivity |
| Dependencies | `requirements.txt` with pinned versions |
| .gitignore | Ignores `.venv/`, `.env`, `__pycache__/`, etc. |

**Completion criterion:** `docker compose up` starts Postgres + pgAdmin.
`GET /health` returns `200 OK`. Alembic connects to the database.

---

## PHASE 1 — Authentication (Admin Access) `[x]`

> Protects the API from external access. Single-operator: only the admin
> (developer) accesses the platform. Not a multi-user system.

| Deliverable | Description |
|-------------|-------------|
| `User` model | id, email, hashed_password, is_active, is_superuser, created_at, updated_at |
| Migration | Alembic: `users` table |
| Schemas | `UserCreate`, `UserRead`, `UserUpdate` (Pydantic v2) |
| Security | bcrypt for password hashing, JWT (access token + refresh token) |
| Router `/auth` | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Dependency | `get_current_user` — extracts JWT from header → returns User |
| Router `/users` | `GET /users/{id}`, `PATCH /users/{id}` (self-service) |

**Completion criterion:** Admin registers, logs in, receives JWT, accesses protected routes.

---

## PHASE 1.5 — Mock E-Commerce Database (Learning) `[x]`

> Database simulating a real platform client.
> Serves as a study instrument and product demonstration.
> This phase is essentially practical: learning SQL, relationships, and how
> real databases behave before building the platform that manages them.

| Deliverable | Description |
|-------------|-------------|
| `ecommerce_mock` database | Second database on the same PostgreSQL — isolated from platform database |
| 5 relational tables | `categories`, `products`, `customers`, `orders`, `order_items` |
| Seed script | `scripts/seed_ecommerce.py` — inserts ~100 realistic mock records |
| SQL exercises | Queries in pgAdmin: JOIN, GROUP BY, aggregations, filters |
| CRUD script | `scripts/explore_ecommerce.py` — demonstrates CRUD via SQLAlchemy |

**Completion criterion:** `ecommerce_mock` database populated. SQL queries running in pgAdmin.
CRUD via SQLAlchemy working. Clear understanding of relationships and joins.

> 📁 Scripts stay in `scripts/` — local folder, listed in `.gitignore`.
> Not part of the API. Study and demonstration tools only.

---

## PHASE 2 — Database Instance Model `[x]`

> The central domain object of the platform: representing each managed database
> as an entity with a complete lifecycle.

| Deliverable | Description |
|-------------|-------------|
| `DatabaseInstance` model | id, name, engine_version, status, host, port, db_name, db_user, connection_uri (encrypted), cpu, memory, storage, notes, created_at, updated_at, deleted_at (soft delete) |
| `InstanceStatus` enum | PENDING → PROVISIONING → RUNNING ↔ STOPPED → DELETING → DELETED / FAILED |
| Migration | Alembic: `database_instances` table |
| Schemas | `InstanceCreate`, `InstanceRead`, `InstanceUpdate` |
| Router `/instances` | `POST`, `GET` (list/detail), `PATCH`, `DELETE` — JWT-protected routes |
| Service layer | Status state machine, transition validation |

**Completion criterion:** Complete CRUD of instances with status state machine.
Each instance represents a client database managed by the platform.

---

## PHASE 2.5 — Security Hardening `[x]`

> Practical API hardening before serving real clients. Phases 0–2 already have
> a functional base (bcrypt, JWT, Pydantic, parameterized SQLAlchemy), but
> additional layers are needed for robust production operation: rate limiting,
> token revocation, at-rest encryption, and registration access control.
>
> **Scope:** Practical security fixes based on the 2026-04-14 audit
> (12 vulnerabilities identified).

| # | Deliverable | Description |
|---|-------------|-------------|
| 1 | **JWT Hardening** | `type` claim (access/refresh), `POST /auth/refresh` endpoint, validation in `get_current_user` |
| 2 | **Token revocation** | `TokenBlacklist` model, middleware check, `POST /auth/logout` endpoint |
| 3 | **Rate limiting** | `slowapi` middleware, limits on `/auth/login` and `/auth/register` |
| 4 | **Registration lockout** | `/auth/register` restricted (first-run setup or admin invite) |
| 5 | **Strong password validation** | Min 12 chars, uppercase, lowercase, digit, special char |
| 6 | **Security headers** | Middleware with `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, etc. |
| 7 | **Fernet encryption** | `encryption.py` module, `FERNET_KEY`, encrypt/decrypt for connection URIs |
| 8 | **Docker & CORS hardening** | Ports restricted to localhost, CORS with specific methods/headers |
| 9 | **Timing-safe auth** | Run bcrypt even when user does not exist |

**Completion criterion:** All routes protected against brute force. JWT tokens
differentiated and revocable. Registration restricted. Passwords validated. Connection URIs
encrypted. Security headers on every response. Docker with restricted ports.

> 💡 **Key concept — Defense in Depth:**
> No single security layer is perfect. The principle is stacking multiple barriers:
> even if rate limiting fails, bcrypt makes brute force slow; even if a token leaks,
> the blacklist allows revoking it; even if someone accesses the database, URIs are
> encrypted. Each layer assumes the previous one can fall.

---

## PHASE 3 — Provisioning Engine `[x]`

> Transform the data model into real databases. Abstract interface that can be
> swapped by environment (dev = Docker, prod = dedicated server).
> Includes database-level security: each instance provisioned with isolated roles
> and permissions — least privilege principle from day one.

| Deliverable | Description |
|-------------|-------------|
| `ProvisionerBase` (ABC) | Interface: create, delete, start, stop, get_status |
| `DockerProvisioner` | Local implementation — creates PostgreSQL containers via Docker SDK |
| Connection strings | Generation + secure storage of connection URI (Fernet encryption) |
| Database roles | Dedicated role per instance with minimum permissions (CONNECT, CRUD on own tables) |
| Integration | Router calls Service → Service calls Provisioner → updates status |
| Status polling | Task that checks if the provisioned instance is healthy |

**Completion criterion:** `POST /instances` creates a real accessible PostgreSQL container.
The provisioned database accepts connections with a dedicated role. Connection URI encrypted
in the platform database.

---

## PHASE 4 — Monitoring & Deep Observability `[x]`

> Total visibility into each managed database. Without monitoring, there is no
> way to guarantee a database is "unbreakable". This phase goes beyond superficial
> metrics — it dives into PostgreSQL's internal views to understand exactly what
> happens inside each database.

| Deliverable | Description |
|-------------|-------------|
| `Metric` model | instance_id, metric_type, value, collected_at |
| `pg_stat_*` collector | Automatic queries to PostgreSQL statistics views |
| Base metrics | Active connections, transactions/s, cache hit ratio, tuples read/written, database size |
| `pg_stat_statements` | Extension integration to track slow and most-executed queries |
| `pg_stat_user_indexes` | Index usage analysis — which are used, which are dead weight |
| `pg_locks` | Active lock monitoring, deadlock detection |
| `EXPLAIN ANALYZE` | Capture and storage of execution plans for slow queries |
| Table bloat | Wasted space estimation for bloated tables and indexes |
| Health polling | Verifies connectivity and responsiveness of each instance periodically |
| Router | `GET /instances/{id}/metrics`, `GET /instances/{id}/health`, `GET /instances/{id}/slow-queries` |

**Completion criterion:** Endpoint returns deep, real metrics: connections, cache hit
ratio, top queries by time/executions, active locks, unused indexes, bloat estimate.
Per-instance health check functional. Ability to capture EXPLAIN for queries.

---

## PHASE 5 — Backup, Restore & PITR `[x]`

> Data protection in two layers: logical backups (pg_dump) for portability
> and physical backups (pg_basebackup + WAL) for Point-in-Time Recovery.
> An "unbreakable" database offers both strategies — one for convenience,
> the other for when every second of data matters.

| Deliverable | Description |
|-------------|-------------|
| `Backup` model | id, instance_id, type (manual/scheduled), strategy (logical/physical), format, status, file_path, size_bytes, created_at, completed_at |
| `BackupSchedule` model | instance_id, cron_expression, retention_days, strategy, is_active |
| `pg_dump` service | Logical backups with custom and plain formats — portable across versions |
| `pg_restore` service | Complete or selective restore from logical backups |
| WAL archiving | `archive_command` configuration to continuously archive WAL segments |
| `pg_basebackup` | Full physical backup as base for PITR |
| Point-in-Time Recovery | Restore to a specific timestamp using base backup + WAL replay |
| Automatic retention | Cleanup of old backups and WAL segments per retention policy |
| Router | `POST /instances/{id}/backups`, `GET` list, `POST /backups/{id}/restore` |

**Completion criterion:** Two functional backup paths: (1) pg_dump/pg_restore for
logical backup, (2) pg_basebackup + WAL for PITR. Ability to restore a database to
any point in time. Old backups automatically cleaned by retention.

> 💡 **Key concept — WAL (Write-Ahead Log):**
> PostgreSQL records EVERY change first in the WAL before applying to data.
> By archiving these logs + a base backup, it is possible to "rewind" the database to
> any second in time. This is what real production databases use.

---

## PHASE 5.5 — Foundation for Growth `[x]`

> Two infrastructure fixes that need to be made before the next phases add more
> routes, endpoints, and containers. Small changes today; costly refactors in PHASE 10.

| Deliverable | Description |
|-------------|-------------|
| **API versioning** | `/api/v1/` prefix on all routers (except `GET /health` — stays at root for load balancer and infra probe compatibility) |
| **Docker resource limits** | `DockerProvisioner.create()` passes `mem_limit` and `nano_cpus` to `containers.run()` using the `memory_mb` and `cpu` fields from `DatabaseInstance` — existing since PHASE 2, previously ignored by the provisioner |

**Completion criterion:** All API routes accessible via `/api/v1/...`. `GET /health`
continues working at the root without prefix. Provisioned containers respect the CPU
and RAM limits configured in the instance — no database can starve others through excessive consumption.

---

## PHASE 6 — Automated Maintenance `[x]`

> PostgreSQL requires regular maintenance to maintain performance. This phase
> automates everything a DBA would do manually: VACUUM, REINDEX, ANALYZE,
> and connection management.

| Deliverable | Description |
|-------------|-------------|
| `MaintenanceTask` model | id, instance_id, task_type, status, scheduled_at, started_at, completed_at, result_summary |
| `MaintenanceSchedule` model | instance_id, task_type, cron_expression, is_active |
| VACUUM automation | Periodic `VACUUM ANALYZE`, `VACUUM FULL` when necessary (bloat detection) |
| REINDEX automation | Bloated index detection + automatic rebuild |
| ANALYZE automation | Statistics update for the query planner |
| Connection management | Idle/leaked connection detection, automatic kill of long-running queries |
| Configuration tuning | Analysis and recommendation of parameters (`shared_buffers`, `work_mem`, `effective_cache_size`, `maintenance_work_mem`) based on instance resources |
| Router | `GET /instances/{id}/maintenance`, `POST /instances/{id}/maintenance/run`, `GET /instances/{id}/config-recommendations` |

**Completion criterion:** Maintenance runs automatically on a configurable schedule.
Problematic connections detected and handled. Bloated indexes rebuilt.
Tuning recommendations generated automatically based on instance CPU/memory.

> 💡 **Key concept — Why VACUUM exists:**
> PostgreSQL uses MVCC (Multi-Version Concurrency Control) — when a row is
> updated or deleted, the old version is NOT immediately erased. VACUUM
> cleans these "dead tuples". Without it, the database grows indefinitely.

---

## PHASE 7 — Alerts & Notifications `[x]`

> Proactive problem detection. Instead of waiting for something to break, the
> platform warns in advance — transforming reaction into prevention.

| Deliverable | Description |
|-------------|-------------|
| `AlertRule` model | id, instance_id, metric_type, condition (gt/lt/eq), threshold, severity (info/warning/critical), is_active |
| `AlertEvent` model | id, rule_id, instance_id, triggered_at, resolved_at, current_value, message |
| Evaluation engine | Compares collected metrics (PHASE 4) against alert rules |
| Default alerts | Disk > 80%, connections > 90% of max, cache hit ratio < 95%, long queries, backup overdue |
| Notifications | Log + webhook (extensible to email/Telegram/Slack in the future) |
| Router | `GET /alerts`, `POST /alerts/rules`, `GET /instances/{id}/alerts` |

> **Note:** "Replication lag" was moved to PHASE 9 — replication does not exist before
> that phase, so the alert has no data to evaluate until then.

**Completion criterion:** Alerts fire automatically when metrics exceed configured
thresholds. Backup overdue by 24h generates a critical alert. Alert history queryable.

**Implemented deliverables:**
- `AlertRule` + `AlertEvent` models with Alembic migration
- 5 metric_types: `connections_ratio`, `cache_hit_ratio`, `db_usage_percent`, `long_query_seconds`, `backup_age_hours`
- 5 conditions: `gt`, `gte`, `lt`, `lte`, `eq`
- 3 severities: `info`, `warning`, `critical`
- Evaluation engine: 60s cycle, auto-fire and auto-resolution of events
- Notification via log + HTTP webhook (configurable via `ALERT_WEBHOOK_URL`)
- Default rule seed via `POST /instances/{id}/alerts/seed-defaults`
- Router with 9 endpoints under `/api/v1/`
- Background loop `alert_evaluation_loop` registered in lifespan

---

## PHASE 8 — Administration Panel `[x]`

> Consolidated view of the entire platform. A single place to see the health
> of all managed databases.

| Deliverable | Description |
|-------------|-------------|
| Dashboard endpoints | Routes that aggregate data from all instances |
| Platform overview | Total instances (by status), active alerts, recent backups, upcoming maintenance |
| `AuditLog` model | user_id, action, resource_type, resource_id, details (JSON), ip_address, timestamp |
| Audit trail | Event emitted automatically by endpoints — no manual annotation in business code |
| Auditable events | **Auth:** `register`, `login`, `logout` · **Instances:** `create`, `status_change`, `delete` · **Backups:** `backup_created`, `restore_initiated`, `schedule_created`, `schedule_deleted` · **Maintenance:** `maintenance_run` |
| Router `/admin` | `GET /admin/dashboard`, `GET /admin/audit-log` |

**Completion criterion:** Dashboard returns consolidated health view of all databases.
Audit log records all relevant platform actions.

**Implemented deliverables:**
- `AuditLog` model with Alembic migration (`e0033cc79913`)
- Indexes: `action`, `timestamp`, composite `(user_id, timestamp)`
- `AuditMiddleware` — automatic interception via path + method regex, no router annotation
- 11 audited actions: `register`, `login`, `logout`, `instance_created`, `instance_status_changed`, `instance_deleted`, `backup_created`, `restore_initiated`, `schedule_created`, `schedule_deleted`, `maintenance_run`
- `user_id` extracted from JWT Bearer header (NULL for login/register — no token in request)
- Service `admin.py`: `write_audit_log()`, `get_dashboard()`, `list_audit_logs()`
- 2 endpoints under `/api/v1/admin/`: `GET /admin/dashboard`, `GET /admin/audit-log`
- `GET /admin/audit-log` filterable by `action`, `resource_type`, and `user_id` with pagination

---

## PHASE 9 — Replication & High Availability `[ ]`

> An "unbreakable" database does not depend on a single instance. Replication
> guarantees that if the primary server fails, there is a copy ready to take over.
> This phase implements PostgreSQL streaming replication — the same mechanism used
> by companies in production.

> **Groundwork already implemented in PHASE 5:** `DockerProvisioner` already configures
> `wal_level=replica`, `archive_mode=on`, and runs `ALTER ROLE {user} WITH REPLICATION`
> on each provisioned database. This phase starts directly at the `pg_hba.conf`
> and `primary_conninfo` configuration — no need to refactor the provisioner.

| Deliverable | Description |
|-------------|-------------|
| `Replica` model | id, primary_instance_id, replica_instance_id, replication_state, lag_bytes, lag_seconds, created_at |
| Streaming replication | Primary configuration (`wal_level=replica`, `max_wal_senders`) + standby (`primary_conninfo`, recovery) |
| Provisioner extension | `DockerProvisioner` gains ability to create replicas linked to a primary |
| Replication monitoring | Query `pg_stat_replication` on primary and `pg_stat_wal_receiver` on standby |
| Lag tracking | Continuous monitoring of delay between primary and replica |
| Promotion | Ability to promote a replica to primary (manual failover) |
| Router | `POST /instances/{id}/replicas`, `GET /instances/{id}/replicas`, `POST /replicas/{id}/promote` |

**Completion criterion:** Primary instance replicates data in real time to a standby.
Replication lag monitored. Replica can be promoted to primary via API.

> 💡 **Key concept — Streaming Replication:**
> The primary sends WAL records to the standby in real time via TCP connection.
> The standby continuously applies WAL records, maintaining a nearly identical copy.
> Different from backup: backup is a snapshot, the replica is a live mirror.

---

## PHASE 10 — Polish, Tests & Deploy `[ ]`

> Making the project production-ready and portfolio-ready.

| Deliverable | Description |
|-------------|-------------|
| Tests | pytest + fixtures for each phase, minimum 80% coverage |
| Dockerfile | Optimized multi-stage build |
| CI/CD | GitHub Actions: lint (ruff), test, build |
| OpenAPI | Custom documentation, tags organized by domain |
| README.md | Professional, with architecture, setup, screenshots |

**Completion criterion:** CI green. README demonstrates the project to recruiters.

---

## PHASE 11 — Multi-Tenancy (Companies & Employees) `[~]`

> Product pivot: the platform evolves from single-operator to **serving multiple
> companies, each with its own employees**. A regular user sees only their own
> company; the **admin superuser** sees and switches between all companies.

**Minimal base — DONE `[x]`** (delivered alongside the frontend Workspace work):

| Deliverable | Description |
|-------------|-------------|
| `Company` model | `companies` table (`backend/src/models/company.py`) + Alembic migration |
| User ↔ Company | `users.company_id` FK (nullable; `NULL` = platform-level/superuser) + `company` relationship (eager `joined`) |
| Superuser gate | `get_current_superuser` (`backend/src/core/dependencies.py`) — first real use of `is_superuser` |
| Companies API | `GET /companies` + `POST /companies`, both superuser-only (`backend/src/routers/companies.py`) |
| `UserRead.company` | `/auth/me` now returns the user's company |
| Workspace UI | `WorkspaceSwitcher` — dropdown for superuser, fixed label for regular user |

**Remaining — TODO `[ ]`**:

| Deliverable | Description |
|-------------|-------------|
| Resource scoping | `company_id` (owner) on `DatabaseInstance` and derived resources; query filtering so each user sees only their company's databases. **Currently resources are NOT scoped by company.** |
| Active-company context | The superuser's selected company (today only persisted in `localStorage`) actually filters the data shown |
| Employee management | Create/list users within a company; assign `user.company_id`; superuser-only company management screens |
| RBAC | Roles beyond `is_superuser` (e.g., company admin vs. member) if needed |
| Audit scoping | Audit log filtered/segmented per company |

**Completion criterion:** A regular user only sees and manages their own company's
databases; the superuser can switch companies and the data follows the selection.

---

## FRONTEND F0 — Next.js Project Setup `[x]`

> First contact with JavaScript/TypeScript. Configure the frontend project
> within the monorepo, integrated with the backend API.

| Deliverable | Description |
|-------------|-------------|
| Scaffold | `npx create-next-app@latest frontend --typescript --tailwind --app` |
| shadcn/ui | UI components installed in the project |
| `lib/api.ts` | Typed HTTP client pointing to `http://localhost:8001/api/v1/` |
| `lib/types.ts` | TypeScript types mirroring backend Pydantic schemas |
| `context/AuthContext.tsx` | Context API to manage JWT token and authentication state |

**Completion criterion:** `npm run dev` starts Next.js at `localhost:3000`. API calls typed.

---

## FRONTEND F1 — Authentication `[x]`

> First real screen. Login → JWT → protected access.

| Deliverable | Description |
|-------------|-------------|
| Login page | `/login` — email + password form, call to `POST /auth/login` |
| JWT storage | Token stored in `localStorage`, injected via `api.ts` in every request |
| Protected routes | Next.js `middleware.ts` redirects to `/login` if not authenticated |
| Logout | Calls `POST /auth/logout`, clears token, redirects to `/login` |

**Completion criterion:** Login functional. Protected routes redirect without token.

---

## FRONTEND F2 — Instance Management `[x]`

> Main platform screen: list, create, and manage databases.

| Deliverable | Description |
|-------------|-------------|
| List | `/instances` — table with status, host, engine, created at |
| Detail | `/instances/[id]` — complete instance info |
| Create | Modal or drawer with new instance form |
| Actions | Stop, start, delete buttons with confirmation |

**Completion criterion:** Instance CRUD functional in UI.

---

## FRONTEND F3 — Metrics & Observability `[~]`

> Real-time visibility into each managed database.

| Deliverable | Description |
|-------------|-------------|
| Charts | Cache hit ratio, active connections — recharts or Chart.js |
| Polling | Automatic update every 30s |
| Slow queries | Table with top queries by execution time |
| Locks | Active lock visualization |

**Completion criterion:** Metrics rendered with automatic updates.

> **Status (parcial `[~]`):** slow queries e locks já renderizados na UI. Os
> **gráficos (cache hit ratio, conexões) seguem stub** — dependem de um endpoint
> de métricas-como-série no backend (mesmo bloqueio citado em F7 para as tabs
> Metrics/Logs). `recharts` já está instalado; falta só a fonte de dados.

---

## FRONTEND F4 — Backups `[x]`

> Visibility and control over each instance's backups.

| Deliverable | Description |
|-------------|-------------|
| List | Backup list per instance (type, status, size, date) |
| Manual trigger | Button to trigger logical or physical backup |
| Restore | Restore form with backup selection |
| Schedule | UI to configure scheduled backup |

**Completion criterion:** Manual and scheduled backup manageable via UI.

---

## FRONTEND F5 — Maintenance & Alerts `[x]`

> Control of automatic tasks and visibility of active alerts.

| Deliverable | Description |
|-------------|-------------|
| Maintenance tasks | VACUUM, REINDEX, ANALYZE history per instance |
| Manual trigger | Trigger maintenance immediately via UI |
| Alert rules | List, create, and deactivate alert rules |
| Alert events | Feed of active and resolved alerts |

**Completion criterion:** Active alerts visible. Maintenance triggerable manually.

---

## FRONTEND F6 — Consolidated Dashboard `[x]`

> Top-level view: entire platform health on one page.
> Depends on `GET /admin/dashboard` (PHASE 8 backend).

| Deliverable | Description |
|-------------|-------------|
| Overview | Total instances by status, active alerts, recent backups |
| Status cards | Card per instance with health indicator |
| Audit log | Table of recent platform actions |
| Navigation | Sidebar or nav with links to all sections |

**Completion criterion:** Dashboard loads consolidated view of all databases.
Complete navigation between platform sections functional.

---

## FRONTEND F7 — SQL Console `[ ]` ⏸️ DEFERRED

> **Status: postponed (decided 2026-06-03).** This is the only remaining frontend
> step that requires **new backend code**, so it was pulled out of the current
> frontend-only sequence to keep momentum. It returns later as a dedicated
> end-to-end block (backend endpoint + UI together) — a strong portfolio piece
> precisely because it is full-stack in a single feature.
>
> The frontend sequence continues without it: after the instance-detail tabs
> (Overview / Backups / Maintenance / Alerts — all done), the next built screen
> is **Audit Log** (`/audit`, reuses existing `getAuditLogs()`, no backend work).
> Note: `Metrics` and `Logs` instance tabs also remain placeholders — they depend
> on backend not yet built (time-series metrics endpoint / per-instance log stream).

| Deliverable | Description |
|-------------|-------------|
| Backend `POST /instances/{id}/query` | Read-only SQL execution against the instance database. **Reuse the existing SELECT-only guard** from `collect_explain` ([backend/src/collectors/pg_stats.py](backend/src/collectors/pg_stats.py)): block `;`, require `startswith select`, blacklist DML/DDL, size cap — extract it into a shared helper and force a `LIMIT`. Layer: router → service → `get_connection()` ([backend/src/services/metrics.py](backend/src/services/metrics.py)) |
| SQL Console screen | `/sql` — instance picker, query editor, results table, error panel |
| Safety | Server rejects non-SELECT / `;` / DML / DDL with `422`; client surfaces the error |

**Completion criterion:** A valid `SELECT` returns rows in the UI; `;`, DML, DDL and
non-SELECT queries are rejected with `422`. The `/sql` placeholder route is wired to
the real feature.

**Why deferred (record):** every other frontend screen reuses an existing typed API
in `lib/api.ts`; the SQL Console alone needs a brand-new endpoint. Building it now
would interleave backend work into a frontend streak, so it is scheduled as a
self-contained full-stack milestone instead.

---

## Dependency Map

```
PHASE 0 (Foundation)
  └─→ PHASE 1 (Auth — Admin Access)
      └─→ PHASE 1.5 (Mock E-Commerce — Learning)
          └─→ PHASE 2 (Instances — Data Model)
                └─→ PHASE 2.5 (Security Hardening)
                      └─→ PHASE 3 (Provisioning — Real Databases)
                            ├─→ PHASE 4 (Monitoring & Observability)
                            │     └─→ PHASE 7 (Alerts & Notifications)
                            └─→ PHASE 5 (Backup, Restore & PITR)
                                  └─→ PHASE 5.5 (Foundation for Growth)
                                        └─→ PHASE 6 (Automated Maintenance)
                                              └─→ PHASE 8 (Administration Panel)
                                                    ├─→ PHASE 9 (Replication & High Availability)
                                                    │     └─→ PHASE 10 (Deploy & Polish)
                                                    └─→ F0 (Frontend Setup)
                                                          └─→ F1 (Auth UI)
                                                                └─→ F2 (Instances UI)
                                                                      └─→ F3 (Metrics UI)
                                                                            └─→ F4 (Backups UI)
                                                                                  └─→ F5 (Maintenance & Alerts UI)
                                                                                        └─→ F6 (Consolidated Dashboard)
                                                                                              └─→ F7 (SQL Console) ⏸️ DEFERRED — needs new backend endpoint
```

## Public / Private Split

| Scope | Phases | Justification |
|-------|--------|---------------|
| **Public repo** (portfolio) | 0 → 10 | Generic database management architecture, no secrets |
| **Private repo(s)** (operations) | — | Real client configs, production credentials, infra-specific scripts |

The public repo contains **all the engineering** with generic implementations.
The proprietary value lies in **operation with real clients**, not in the codebase.
