from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKSTREAM_", env_file=".env", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    app_name: str = "Workstream"
    database_url: str = "postgresql+psycopg://workstream:workstream@localhost:5432/workstream"
    async_database_url: str = (
        "postgresql+psycopg_async://workstream:workstream@localhost:5432/workstream"
    )
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: SecretStr = SecretStr("local-only-change-me-please-32-chars")
    jwt_issuer: str = "workstream"
    jwt_audience: str = "workstream-api"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    cors_origins: list[str] = []
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    email_from: str = "noreply@workstream.local"
    public_url: str = "http://localhost:8000"
    log_json: bool = False

    @model_validator(mode="after")
    def validate_production(self) -> Self:
        if self.environment == "production":
            if self.jwt_secret.get_secret_value().startswith("local-only"):
                raise ValueError("production requires a non-default JWT secret")
            if not self.log_json:
                raise ValueError("production requires JSON logging")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
