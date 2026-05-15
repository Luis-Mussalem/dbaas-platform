# Error History

> Record each relevant error found during development.
> Root cause + resolution — to avoid recurrence.

| # | Date | Error | Root Cause | Resolution |
|---|------|-------|------------|------------|
| 1 | 2026-04-08 | `pgAdmin` restart loop | `dpage/pgadmin4` recent version rejects `.local` domains in email | Change `admin@dbaas.local` to `admin@admin.com` (later `admin@dbaas.dev`) |
| 2 | 2026-04-08 | `(trapped) error reading bcrypt version` | `passlib 1.7.4` tries to access `bcrypt.__about__` removed in v4.x | Remove `passlib`, use `bcrypt` directly via `bcrypt.hashpw` / `bcrypt.checkpw` |
| 3 | 2026-04-08 | `RuntimeError: Form data requires python-multipart` | `OAuth2PasswordRequestForm` depends on `python-multipart` not included in `requirements.txt` | Install and add `python-multipart==0.0.9` to `requirements.txt` |
| 4 | 2026-04-14 | pgAdmin `password authentication failed for user "dbaas"` | `.env` file with CRLF line endings (Windows). Copy-paste included invisible `\r` in password (33 chars vs expected 32) | `sed -i 's/\r$//' .env` to convert CRLF → LF. Verify LF in the VS Code status bar |
| 5 | 2026-04-30 | `collect_explain` accepted `SELECT * FROM (DELETE ...)` | Validation only with `startswith("select")` — did not block DML embedded in subqueries | `_EXPLAIN_BLOCKED` blocklist, 8000 char limit, prohibition of `;` in `backend/src/collectors/pg_stats.py` |
| 6 | 2026-04-30 | `DATABASE_URL` broke with passwords containing `@`, `#`, `/` | f-string without password encoding → SQLAlchemy fails to parse host from URL | `urllib.parse.quote(password, safe="")` in the `DATABASE_URL` property in `backend/src/core/config.py` |
| 7 | 2026-04-30 | `token_blacklist` grew indefinitely | No task removed already-expired tokens from the table | `cleanup_expired_tokens()` in `backend/src/services/auth.py` + daily call in `status_poller` |
| 8 | 2026-04-30 | `metrics` table grew indefinitely | No retention policy — ~864k rows/day with 10 RUNNING instances | 30-day retention + daily cleanup in `backend/src/services/metrics_poller.py` |
| 9 | 2026-04-30 | `ExplainRequest.query` without `max_length` in Pydantic schema | Schema and collector misaligned — Pydantic accepted arbitrarily long strings | `max_length=8000` added to field in `backend/src/schemas/metric.py` |
| 10 | 2026-05-11 | `kill_idle_connections` failed with "permission denied for function pg_terminate_backend" | Provisioned role without `pg_signal_backend` permission — required to call `pg_terminate_backend` / `pg_cancel_backend` on other roles' sessions | `GRANT pg_signal_backend TO {role}` added to `DockerProvisioner` in `backend/src/services/provisioning/docker_provisioner.py` |
