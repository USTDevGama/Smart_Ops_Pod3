from functools import lru_cache
from typing import Literal

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
    # Scanned pages are read through Docling. "rapidocr" needs nothing installed; "tesseract"
    # needs the tesseract binary.
    ocr_enabled: bool = True
    ocr_engine: Literal["tesseract", "rapidocr"] = "rapidocr"
    ocr_lang: str = "eng"
    tesseract_cmd: str = "tesseract"  # name on PATH, or the full path to tesseract.exe
    # Figures become their own segments: caption, text read inside, and the figure type.
    figures_enabled: bool = True
    # A vision model also writes a description. Off by default: a small model invented a chart
    # value in testing, so its text is always marked unverified. Downloads a model on first use.
    figure_descriptions: bool = False
    # When set, each ingested proposal gets a folder here with Docling's own output, the stored
    # segments and the cropped figures. That is proposal content: keep it out of git and delete
    # it after use.
    ingest_debug_dir: str | None = None
    segment_max_chars: int = 1200
    llm_provider: str = "fake"
    retention_days: int = 30
    max_llm_calls_per_session: int = 40
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
