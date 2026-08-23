from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ForgeGraph API"
    environment: str = Field(
        default="development",
        pattern="^(development|staging|production|test)$",
    )
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,https://forgegraph-unihack-hack2skill.vercel.app"
    max_upload_bytes: int = 25 * 1024 * 1024
    max_rows_per_job: int = 10_000
    allowed_upload_extensions: str = ".csv,.xlsx"
    database_url: str = "postgresql+psycopg://forgegraph:forgegraph@localhost:5432/forgegraph"
    object_storage_bucket: str = "forgegraph-local"
    object_storage_endpoint: str | None = None
    ai_provider: str = "openrouter"
    ai_model: str = "openai/gpt-4o-mini"
    ai_timeout_seconds: float = 30.0
    manufacturer_domains: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_extension_set(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.allowed_upload_extensions.split(",")
            if item.strip()
        }

    @property
    def manufacturer_domain_set(self) -> set[str]:
        return {
            item.strip().lower() for item in self.manufacturer_domains.split(",") if item.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
