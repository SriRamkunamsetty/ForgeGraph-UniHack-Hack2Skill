from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ForgeGraph API"
    environment: Literal["development", "staging", "production", "test"] = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,https://forgegraph-unihack-hack2skill.vercel.app"

    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    max_rows_per_job: int = Field(default=10_000, ge=1)
    allowed_upload_extensions: str = ".csv,.xlsx"
    max_fetch_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    request_timeout_seconds: float = Field(default=30.0, gt=0)

    storage_backend: Literal["memory", "postgres"] = "memory"
    database_url: str = "postgresql+psycopg://forgegraph:forgegraph@localhost:5432/forgegraph"
    database_password: str | None = None
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    auto_create_schema: bool = False
    redis_url: str | None = None

    object_storage_backend: Literal["local", "gcs", "s3"] = "local"
    object_storage_bucket: str = "forgegraph-local"
    object_storage_prefix: str = "forgegraph"
    object_storage_endpoint: str | None = None
    gcp_project_id: str | None = None
    gcp_region: str = "us-central1"

    job_execution_mode: Literal["inline", "cloud_tasks"] = "inline"
    cloud_tasks_queue: str = "forgegraph-jobs"
    cloud_tasks_location: str = "us-central1"
    cloud_tasks_dispatch_url: str | None = None
    cloud_tasks_service_account: str | None = None
    internal_worker_token: str | None = None

    ai_provider: Literal["disabled", "openai_compatible", "vertex_ai"] = "disabled"
    ai_model: str = "gemini-2.5-flash"
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_timeout_seconds: float = Field(default=60.0, gt=0)

    manufacturer_domains: str = ""
    retrieval_user_agent: str = "ForgeGraphBot/1.0 (+https://forgegraph.example.com/bot)"
    retrieval_max_redirects: int = Field(default=3, ge=0, le=10)

    auth_enabled: bool = False
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_jwks_url: str | None = None

    @field_validator("cors_origins", "manufacturer_domains", mode="before")
    @classmethod
    def normalize_csv_setting(cls, value: object) -> str:
        return str(value or "")

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

    @property
    def postgres_enabled(self) -> bool:
        return self.storage_backend == "postgres"

    @property
    def gcs_enabled(self) -> bool:
        return self.object_storage_backend == "gcs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
