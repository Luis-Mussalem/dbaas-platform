from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "DBaaS Platform"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Database
    POSTGRES_USER: str = "dbaas"
    POSTGRES_PASSWORD: str = "dbaas_secret"
    POSTGRES_DB: str = "dbaas"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()