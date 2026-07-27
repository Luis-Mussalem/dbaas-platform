# syntax=docker/dockerfile:1

# =============================================================================
# Stage 1 — builder: installs the Python dependencies in an isolated virtualenv.
# Separating build from runtime keeps the final image small: compilation
# tools and pip caches stay in this stage and never reach the final image.
# =============================================================================
# Base pinned to bookworm (Debian 12) on purpose: the floating
# python:3.12-slim tag already migrated to trixie (Debian 13), whose libldap breaks the
# PGDG PostgreSQL client install. Pinning keeps the build reproducible.
FROM python:3.12-slim-bookworm AS builder

# - PYTHONDONTWRITEBYTECODE: no .pyc generated during the build (cleaner image)
# - PIP_NO_CACHE_DIR / PIP_DISABLE_PIP_VERSION_CHECK: faster, lighter build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Creates a dedicated venv at /opt/venv. Copying the whole venv to the runtime
# stage is simpler and more predictable than recompiling there.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copying only requirements first takes advantage of Docker's layer cache:
# as long as requirements.txt doesn't change, this layer (the priciest one) is reused.
COPY requirements.txt .
RUN pip install -r requirements.txt


# =============================================================================
# Stage 2 — runtime: minimal final image that just runs the application.
# =============================================================================
FROM python:3.12-slim-bookworm AS runtime

# - PYTHONUNBUFFERED: logs show up right away (no buffering) — essential in a container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# postgresql-client-16 provides pg_dump, pg_restore and pg_basebackup, used by the
# backup service (PHASE 5). The version needs to be >= the managed server's
# (postgres:16) — hence the official PGDG repository, since Debian
# bookworm ships only client 15 by default.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*

# Copies the ready-made venv from the builder stage — no pip install or toolchain here.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Non-root user (defense in depth): if the application is compromised,
# the attacker has no root privileges inside the container.
RUN useradd --create-home --uid 10001 appuser

# Application code + migrations. Copied last because it changes more
# often than the dependencies — preserves the cache of the layers above.
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini ./

USER appuser

EXPOSE 8001

# Healthcheck hits the same GET /health used by the infra/load balancer.
# Uses urllib (stdlib) to avoid depending on curl in the final image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"

# Starts the API. Migrations (alembic upgrade head) run as a separate
# deploy step — not in the CMD — to avoid coupling app startup to migration.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
