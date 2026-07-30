# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-07-30

First complete release. Every phase on the [roadmap](ROADMAP.md) is delivered:
backend PHASE 0–11 and frontend F0–F8.

### Provisioning

- Docker-backed provisioning engine: each managed database is a real PostgreSQL 16
  container with its own volume, port and credentials.
- Full lifecycle — create, start, stop, restart, soft-delete — with the instance
  status reconciled by a background poller, so containers that die out of band are
  picked back up.
- Connection credentials encrypted at rest with Fernet; the plaintext URI is never
  stored or logged.

### Monitoring & observability

- Metrics collected per instance from `pg_stat_*`: connections, cache hit ratio,
  database size, transaction throughput and per-query statistics.
- Time-series history with a selectable window (15m/1h/6h/24h), plus fleet-wide
  KPIs — queries/s, real P95 latency from `pg_stat_statements`, storage growth and
  30-day uptime computed from `instance_status_history`.
- Slow queries, active locks and container logs exposed per instance.

### Backup & recovery

- Logical backups (`pg_dump`) and physical backups (`pg_basebackup`) with WAL
  archiving for point-in-time recovery.
- Scheduled backups with a retention policy, including indefinite retention.
- Restore flow with pre-flight validation.

### Automated operations

- Scheduled `VACUUM`/`ANALYZE`/`REINDEX` maintenance driven by cron expressions,
  with a full execution history.
- Threshold alerts on connections, disk usage and replication lag, each with an
  evaluation loop that opens and resolves alerts automatically.

### Replication & high availability

- Streaming standbys created with `pg_basebackup -R`; the primary gains the
  required `max_wal_senders`/`hot_standby` settings and a `pg_hba.conf` entry
  on demand.
- Live replication-lag monitoring (bytes and seconds) and a manual failover flow
  via `pg_promote()`.

### Multi-tenancy & security

- Companies and employees, with instances and every derived resource scoped by
  `company_id`; the superuser switches workspace from the top bar.
- Two-rule authorization model: an explicit three-state read scope (unrestricted,
  one company, or empty) and a write gate where members observe and admins operate.
  A test walks every mutating route so a missing gate fails the suite.
- JWT auth in HttpOnly cookies, re-authentication for credential changes, audit
  logging scoped per company, and error redaction so infrastructure details never
  reach the API surface.

### Interface

- Next.js 16 dashboard (App Router, React 19, Tailwind v4) with a fleet overview,
  instance detail tabs, backups, maintenance, alerts, employees, audit log and a
  guarded SQL console.
- Global ⌘K command palette, skeleton loaders, toast feedback and confirmation
  dialogs.
- Bilingual EN/PT via next-intl with the locale in a cookie; message parity is
  enforced in CI.

### Demo

- The public demo boots with a populated fleet and keeps a continuous baseline
  workload running, so the dashboard is alive on first load rather than empty.
- The demo is disclosed in the UI — a persistent banner plus an *About this demo*
  page — and gated behind `DEMO_MODE`.

### Delivery

- One-command full-stack Docker Compose; `.env.example` is copy-and-run.
- 3-job CI pipeline: backend lint and tests, frontend build and typecheck, and the
  i18n parity check.
- 387 backend tests plus 11 Playwright E2E smoke tests.

[1.0.0]: https://github.com/Luis-Mussalem/dbaas-platform/releases/tag/v1.0.0
