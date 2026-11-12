from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SAFE_DEV_AUTH_ENVS = {"local", "dev"}


class Settings(BaseSettings):
    """All settings come from PODC_* environment variables (or .env)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PODC_", extra="ignore")

    env: str = "local"
    # Level for the app's own log lines (`llm call ... Ns`, `agent ... ok`); see app/main.py.
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://podc:podc@localhost:5432/podc"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    blob_dir: str = "./storage"
    max_upload_mb: int = 10
    # True runs the ingest and post-session scoring steps inside the API call (no Redis or worker
    # needed). Local use only.
    ingest_inline: bool = False
    # "fake" = scripted/placeholder, no key. Anything else = the real client (`ProviderLLM`).
    llm_provider: str = "fake"
    # Claude, direct, through Azure AI Foundry, or through an internal Anthropic-compatible
    # gateway. The key is a SecretStr so it never shows up in a repr, a log line or an error. Set
    # these in .env (never committed). Exactly one of anthropic_gateway_url / anthropic_use_azure
    # applies; gateway_url wins if both are set.
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5"  # used when not on Azure and no gateway is set
    anthropic_use_azure: bool = False
    anthropic_azure_endpoint: str | None = None
    anthropic_azure_deployment: str | None = None  # the model name to send when on Azure
    # An internal reverse proxy that speaks the plain Anthropic /v1/messages shape (not the
    # Azure-AI-Foundry-specific one). anthropic_model is the model/deployment id to send it.
    anthropic_gateway_url: str | None = None
    anthropic_timeout_s: float = 30.0
    # How to turn thinking off, since this is model-generation-specific and the three shapes
    # above can each point at a different model: most Claude models accept {"type": "disabled"},
    # but Claude Sonnet 5.5 rejects it and needs {"type": "between_tools"} instead. Set this to
    # match whatever model the deployment actually points at.
    anthropic_thinking_off: Literal["disabled", "between_tools"] = "disabled"
    # Route the model call through a local proxy (e.g. an SSH -D SOCKS tunnel to a host that can
    # reach the gateway, when this machine cannot): "socks5h://127.0.0.1:1080" or
    # "http://127.0.0.1:8080". Leave unset to connect directly.
    anthropic_proxy_url: str | None = None
    # Fallback source for anthropic_api_key: an Azure Key Vault secret, fetched at call time via
    # an app registration's client-credentials flow (no key ever sits in a config file). Used only
    # when anthropic_api_key is unset; a direct key always wins. All five must be set together.
    azure_vault_url: str | None = None
    azure_vault_secret_name: str | None = None
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: SecretStr | None = None
    retention_days: int = 30
    dev_auth_enabled: bool = True
    # Local folder holding the program's confidential seed pack. Never inside this repo.
    seed_dir: str | None = None

    @field_validator("anthropic_api_key", "azure_client_secret", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value):
        """A blank value (`PODC_ANTHROPIC_API_KEY=` in an env file) means "not set". Without this
        it would count as a key, and because a direct key beats the Key Vault, one blank line
        would silently switch the vault off and send an empty key to the model."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def assert_safe_for_env(self) -> None:
        """The dev-only fake login must never be on outside local/dev."""
        if self.dev_auth_enabled and self.env not in SAFE_DEV_AUTH_ENVS:
            raise RuntimeError(
                f"PODC_DEV_AUTH_ENABLED=true is not allowed when PODC_ENV={self.env!r}"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
