from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import os


class Settings(BaseSettings):
    # Database (DATABASE_URL; we convert to asyncpg and strip Neon SSL params for asyncpg)
    database_url: str = Field(
        default="postgresql+asyncpg://creditapp:creditapp@localhost:5432/credit_analysis",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    database_require_ssl: bool = False

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("REDIS_URL", "redis_url"),
    )

    # Object storage — STORAGE_* (your .env) or OBJECT_STORAGE_*
    object_storage_url: str = Field(
        default="",
        validation_alias=AliasChoices("OBJECT_STORAGE_URL", "object_storage_url"),
    )
    object_storage_access_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("STORAGE_ACCESS_KEY_ID", "OBJECT_STORAGE_ACCESS_KEY"),
    )
    object_storage_secret_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("STORAGE_SECRET_ACCESS_KEY", "OBJECT_STORAGE_SECRET_KEY"),
    )
    object_storage_bucket: str = Field(
        default="credit-docs",
        validation_alias=AliasChoices("STORAGE_BUCKET_NAME", "OBJECT_STORAGE_BUCKET"),
    )
    object_storage_use_ssl: bool = Field(
        default=True,
        validation_alias=AliasChoices("OBJECT_STORAGE_USE_SSL", "object_storage_use_ssl"),
    )
    storage_region: str = Field(
        default="eu-north-1",
        validation_alias=AliasChoices("STORAGE_REGION", "storage_region"),
    )
    storage_provider: str = Field(
        default="s3",
        validation_alias=AliasChoices("STORAGE_PROVIDER", "storage_provider"),
    )

    # Auth — SECRET_KEY or JWT_SECRET
    jwt_secret: str = Field(
        default="change-me-in-production",
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET"),
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # LLM
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.0
    log_llm_prompts: bool = Field(
        default=False,
        validation_alias=AliasChoices("LOG_LLM_PROMPTS", "log_llm_prompts"),
    )

    # App
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins"),
    )
    allowed_hosts: str = Field(
        default="localhost,127.0.0.1",
        validation_alias=AliasChoices("ALLOWED_HOSTS", "allowed_hosts"),
    )

    @model_validator(mode="after")
    def ensure_asyncpg_and_ssl(self) -> "Settings":
        """Use async driver and strip sslmode/channel_binding (asyncpg uses connect_args ssl=True)."""
        url = self.database_url
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        parsed = urlparse(url)
        if parsed.query:
            q = parse_qsl(parsed.query)
            self.database_require_ssl = any(k == "sslmode" and v == "require" for k, v in q)
            new_q = [(k, v) for k, v in q if k not in ("sslmode", "channel_binding")]
            new_query = urlencode(new_q)
            url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        self.database_url = url
        return self

    class Config:
        env_file = (".env", "../.env")
        extra = "ignore"
        populate_by_name = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
