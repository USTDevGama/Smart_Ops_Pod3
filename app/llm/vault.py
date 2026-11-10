"""Fetches the real model's API key from Azure Key Vault via an app registration's
client-credentials flow, so the key never has to sit in a config file.

Two calls: an AAD token for the Key Vault data plane, then the secret itself
(`app/config.py`'s `PODC_AZURE_*` settings). The result is cached in memory per
(tenant, client, vault, secret name), so a long-running process asks only once. Nothing here
persists anything to disk or logs the token or the secret value. Errors carry an HTTP status
only - never the vault's response body (which could echo back parts of the request).
"""

import httpx

from app.config import Settings
from app.llm.base import LLMError

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_VAULT_SCOPE = "https://vault.azure.net/.default"
_VAULT_API_VERSION = "7.4"

CacheKey = tuple[str, str, str, str]
_cache: dict[CacheKey, str] = {}


def fetch_secret(settings: Settings, *, client: httpx.Client | None = None) -> str:
    """The vault secret's value. Raises `LLMError` if the vault settings are incomplete or
    either call fails."""
    if not _configured(settings):
        raise LLMError("vault is not fully configured (set all five PODC_AZURE_* settings)")

    # _configured() above already proved every field here is set.
    key: CacheKey = (
        settings.azure_tenant_id, settings.azure_client_id,
        settings.azure_vault_url, settings.azure_vault_secret_name,
    )
    if key in _cache:
        return _cache[key]

    http = client or httpx.Client(timeout=20.0)
    token = _get_token(http, settings)
    secret = _get_secret(http, settings, token)
    _cache[key] = secret
    return secret


def _configured(settings: Settings) -> bool:
    return bool(
        settings.azure_tenant_id and settings.azure_client_id
        and settings.azure_vault_url and settings.azure_vault_secret_name
        and settings.azure_client_secret
    )


def _get_token(http: httpx.Client, settings: Settings) -> str:
    assert settings.azure_client_secret is not None  # _configured() already checked this
    url = _TOKEN_URL.format(tenant=settings.azure_tenant_id)
    try:
        response = http.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.azure_client_id,
                "client_secret": settings.azure_client_secret.get_secret_value(),
                "scope": _VAULT_SCOPE,
            },
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"vault login failed (HTTP {exc.response.status_code})") from None
    except httpx.HTTPError as exc:
        raise LLMError(f"vault login failed ({type(exc).__name__})") from None
    return response.json()["access_token"]


def _get_secret(http: httpx.Client, settings: Settings, token: str) -> str:
    url = f"{settings.azure_vault_url.rstrip('/')}/secrets/{settings.azure_vault_secret_name}"
    try:
        response = http.get(
            url,
            params={"api-version": _VAULT_API_VERSION},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"secret fetch failed (HTTP {exc.response.status_code})") from None
    except httpx.HTTPError as exc:
        raise LLMError(f"secret fetch failed ({type(exc).__name__})") from None
    return response.json()["value"]
