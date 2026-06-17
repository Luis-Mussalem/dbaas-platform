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
| 11 | 2026-04-28 | `get_current_user` crashed with unhandled `ValueError` on malformed JWT `sub` field | `uuid.UUID(user_id)` raises `ValueError` on non-UUID strings; exception was uncaught, producing a 500 instead of 401 | Wrapped call in `try/except ValueError` and raise `credentials_exception` in `backend/src/core/dependencies.py` |
| 12 | 2026-05-15 | `AlertRule` PATCH silently ignored fields explicitly set to `None` | `model_dump(exclude_none=True)` also drops intentional `None` updates; only `exclude_unset=True` should be used for PATCH | Changed to `model_dump(exclude_unset=True)` in `backend/src/services/alert.py` |
| 13 | 2026-05-15 | `ImportError` on startup — `get_db` not found in alerts router | Wrong import path: `from src.core.dependencies import get_db` instead of `from src.core.database import get_db` | Corrected import in `backend/src/routers/alerts.py` |
| 14 | 2026-05-26 | `POST /instances/{id}/change_status` returned 422 — body rejected | Endpoint expected a raw string; client sent a JSON object `{"action": "start"}` | Introduced `StatusAction(BaseModel)` schema and `_ACTION_TO_STATUS` map in `backend/src/routers/instances.py` |
| 15 | 2026-05-26 | Logout `401` when called without supplying `refresh_token` / with missing `Authorization` header | `LogoutRequest.refresh_token` was required; auth-header guard absent | Made `refresh_token` optional; added early check for missing/malformed `Authorization` header in `backend/src/routers/auth.py` |
| 16 | 2026-05-26 | Frontend `InstanceStatus` type missing `deleted` and `failed` values — UI crashed on those states | `lib/types.ts` union didn't include all backend enum values; `STATUS_STYLES` map raised `undefined` key error | Added `"deleted"` and `"failed"` to `InstanceStatus` union and `STATUS_STYLES` map in `frontend/lib/types.ts` and `frontend/components/InstanceCard.tsx` |
| 17 | 2026-05-29 | Inactive users could log in successfully | `authenticate_user` only checked password hash; never checked `user.is_active` | Added `if not user.is_active: return None` guard in `backend/src/services/auth.py` |
| 18 | 2026-06-02 | `ReferenceError: require is not defined` during Next.js SSR for metrics chart | `recharts` uses CommonJS `require` internally; Turbopack SSR doesn't support it | Switched to `dynamic(import(...), { ssr: false })` for `MetricsChart` in `frontend/app/(dashboard)/instances/[id]/page.tsx` |
| 19 | 2026-06-02 | Instance `connection_uri` pointed to stale port after stop + start | Docker reassigns a new host port on each `start`; the persisted URI was never updated | Added `_sync_connection_port` to rewrite the encrypted URI and added `_wait_until_database_ready` readiness poll before returning from `start` / `restart` in `backend/src/services/provisioning/docker_provisioner.py` |
| 20 | 2026-06-09 | `GET /users/{id}` allowed any authenticated user to read another user's record (IDOR) | No object-level authorization; only authentication was checked | Added `if current_user.id != user_id and not current_user.is_superuser: 403` in `backend/src/routers/users.py`; also capped monitoring query time and replaced 503 internals leak with generic message |
| 21 | 2026-06-12 | `environment` Alembic migration failed with `invalid input value for enum type` | Migration used lowercase labels (`production`, `staging`) but SQLAlchemy emits the Python enum name in uppercase (`PRODUCTION`, `STAGING`) | Changed `postgresql.ENUM(...)` labels to uppercase in `backend/alembic/versions/b2c4f6a8d0e1_*.py` |
| 22 | 2026-06-16 | Backup/restore failure leaked `pg_dump` stderr (host, port, internal details) to the API response | `RuntimeError(str(exc))` passed subprocess output directly into `HTTPException.detail` | Catch `RuntimeError`, log `str(exc)` server-side, return generic `"Backup failed"` message in `backend/src/routers/backups.py` |
| 23 | 2026-06-16 | `auth_token` cookie missing `Secure` flag in HTTPS contexts | Cookie set with only `SameSite=Lax`; `Secure` was never applied | Added conditional `; Secure` when `window.location.protocol === "https:"` in `frontend/context/AuthContext.tsx` and `frontend/lib/api.ts` |

---

**Decision log**

| Date | Decision | Context |
|------|----------|---------|
| 2026-06-16 | `/admin` dashboard kept open to any authenticated user | `ec6ad01` gated it behind `is_superuser`; `aeeefd9` reverted — the superuser gate belongs in the tenancy phase (PHASE 11) where roles are fully defined, not bolted on prematurely |
