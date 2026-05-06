"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False
    app_name: str = "turfify"
    api_prefix: str = "/v1"

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/turfify"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    jwt_secret: str = Field(default="dev-only-change-me")
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30

    cors_origins: str = "http://localhost:3000"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    email_provider: Literal["noop", "resend"] = "noop"

    # Future-phase env (kept here so schema is complete from day one)
    initial_admin_phone: str = ""
    firebase_project_id: str = ""
    firebase_credentials_path: str = ""
    bkash_mode: Literal["sandbox", "live"] = "sandbox"
    bkash_base_url: str = ""
    bkash_app_key: str = ""
    bkash_app_secret: str = ""
    bkash_username: str = ""
    bkash_password: str = ""
    bkash_callback_url: str = ""
    sentry_dsn: str = ""
    resend_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
