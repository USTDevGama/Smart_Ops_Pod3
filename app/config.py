from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

SAFE_DEV_AUTH_ENVS = {"local", "dev"}


class Settings(BaseSettings):
    """All settings come from PODC_* environment variables (or .env)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PODC_", extra="ignore")

    env: str = "local"
    database_url: str = "postgresql+psycopg://podc:podc@localhost:5432/podc"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    blob_dir: str = "./storage"
    max_upload_mb: int = 10
    # True runs the ingest and post-session scoring steps inside the API call (no Redis or worker
    # needed). Local use only.
    ingest_inline: bool = False
    llm_provider: str = "fake"
    retention_days: int = 30
    dev_auth_enabled: bool = True
    # Local folder holding the program's confidential seed pack. Never inside this repo.
    seed_dir: str | None = None

    def assert_safe_for_env(self) -> None:
        """The dev-only fake login must never be on outside local/dev."""
        if self.dev_auth_enabled and self.env not in SAFE_DEV_AUTH_ENVS:
            raise RuntimeError(
                f"PODC_DEV_AUTH_ENABLED=true is not allowed when PODC_ENV={self.env!r}"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
