from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote as _urlquote

# backend/src/core/config.py → parents[3] = project root (dbaas-platform/)
_PROJECT_ROOT = Path(__file__).parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "DBaaS Platform"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Database
    POSTGRES_USER: str = "dbaas"
    POSTGRES_PASSWORD: str = "change-me"
    POSTGRES_DB: str = "dbaas"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Encryption (Fernet) — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FERNET_KEY: str = "change-me-generate-a-real-fernet-key"

    # Registration lockout
    REGISTRATION_ENABLED: bool = False

    # Backup
    BACKUP_DIR: str = str(_PROJECT_ROOT / "data" / "backups")
    # Root directory where all backups are stored on the host.
    # Each instance has its own subfolder: {BACKUP_DIR}/{instance_id}/
    # Subfolders: logical/ (pg_dump .dump files), physical/ (pg_basebackup dirs), wal/ (WAL archive)
    # In production, replace with a path that has plenty of disk space.

    # Alerts
    # Optional URL for webhook delivery when an alert fires or is resolved.
    # If not set, alerts are only logged to the application log.
    # The payload sent is JSON with: event, severity, metric_type, instance_id,
    # current_value, threshold, message, triggered_at, resolved_at.
    ALERT_WEBHOOK_URL: str | None = None

    # Metrics poller cadence: how often we collect and persist
    # metrics for each RUNNING instance. Production uses 60s (cheap; most
    # metrics move slowly). The demo lowers it to 15s (see .env/.env.example) so the
    # dashboard — queries/s, connections, latency — updates visibly
    # live instead of jumping every minute; 15s matches the workload simulator's
    # cycle, so each window covers a full round of commits.
    METRICS_POLL_INTERVAL_SECONDS: int = 60

    # Demo mode — live demo fleet by default
    # Exposes /api/v1/demo and starts the "live demo" director + the load generator.
    # Unlike the old model (fleet started empty), here the seed already populates the
    # fleet with history and the generator keeps a continuous baseline load, so the
    # dashboard shows a live platform right on first login. The "View live"
    # button just amplifies this for ~1 min. With DEMO_MODE=false the endpoints
    # respond 404 and the loops don't start.
    DEMO_MODE: bool = True
    # Load generator cadence. 5s (not 15s) so commits go out in
    # smaller, more frequent bursts: each poller collection window (15s)
    # covers ~3 bursts, which avoids queries/s aliasing (poll and burst with the
    # same period would beat against each other). See _QUERIES_PER_ACTIVE_CONN, sized together with this.
    DEMO_WORKLOAD_INTERVAL_SECONDS: int = 5
    # Cap on simultaneous connections per production instance (staging uses ~half).
    # Each connection is a PostgreSQL backend (~10 MB): 14 × 3 prod + 7 × 3 staging
    # ≈ 60 connections across the whole fleet. Lower this if the machine is modest.
    DEMO_WORKLOAD_MAX_CONNECTIONS: int = 14

    # Provisioning — Docker
    # Password for the postgres superuser inside each provisioned container.
    # No default intentionally: pydantic-settings raises a ValidationError at
    # startup if this variable isn't set in .env, preventing the
    # application from accidentally running with a known/weak password.
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    PROVISIONER_SUPERUSER_PASSWORD: str

    @model_validator(mode="after")
    def check_secrets_are_changed(self) -> "Settings":
        if "change-me" in self.JWT_SECRET_KEY:
            raise ValueError(
                "JWT_SECRET_KEY must be changed from the default placeholder. "
                'Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if "change-me" in self.FERNET_KEY:
            raise ValueError(
                "FERNET_KEY must be changed from the default placeholder. "
                'Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        # Fails early, at startup, if FERNET_KEY isn't a valid Fernet key
        # (e.g. the old .env.example placeholder). Without this, the error would only
        # show up on the first encrypt/decrypt — when provisioning/reading an instance.
        from cryptography.fernet import Fernet

        try:
            Fernet(self.FERNET_KEY.encode())
        except Exception as exc:
            raise ValueError(
                "FERNET_KEY is not a valid Fernet key (must be 32 url-safe "
                "base64-encoded bytes). Generate with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from exc
        if "change-me" in self.POSTGRES_PASSWORD:
            raise ValueError(
                "POSTGRES_PASSWORD must be changed from the default placeholder. "
                'Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return self

    @property
    def DATABASE_URL(self) -> str:
        password = _urlquote(self.POSTGRES_PASSWORD, safe="")
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()