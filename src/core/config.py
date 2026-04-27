from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Provisioning — Docker
    # Senha do superuser postgres dentro de cada container provisionado.
    # Sem default intencional: pydantic-settings levanta ValidationError no
    # startup se esta variável não estiver definida no .env, impedindo a
    # aplicação de rodar com uma senha conhecida/fraca acidentalmente.
    # Gerar com: python -c "import secrets; print(secrets.token_urlsafe(32))"
    PROVISIONER_SUPERUSER_PASSWORD: str

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()