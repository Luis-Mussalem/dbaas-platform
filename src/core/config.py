from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote as _urlquote


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "PalmTreeDB"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Database
    POSTGRES_USER: str = "palmtreedb"
    POSTGRES_PASSWORD: str = "change-me"
    POSTGRES_DB: str = "palmtreedb"
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
    BACKUP_DIR: str = "./data/backups"
    # Diretório raiz onde todos os backups são armazenados no host.
    # Cada instância tem sua própria subpasta: {BACKUP_DIR}/{instance_id}/
    # Subpastas: logical/ (pg_dump .dump files), physical/ (pg_basebackup dirs), wal/ (WAL archive)
    # Em produção, usar caminho absoluto com bastante espaço em disco.

    # Provisioning — Docker
    # Senha do superuser postgres dentro de cada container provisionado.
    # Sem default intencional: pydantic-settings levanta ValidationError no
    # startup se esta variável não estiver definida no .env, impedindo a
    # aplicação de rodar com uma senha conhecida/fraca acidentalmente.
    # Gerar com: python -c "import secrets; print(secrets.token_urlsafe(32))"
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
        return self

    @property
    def DATABASE_URL(self) -> str:
        password = _urlquote(self.POSTGRES_PASSWORD, safe="")
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()