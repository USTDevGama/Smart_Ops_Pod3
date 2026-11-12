"""The Key Vault fallback: two HTTP calls, cached, errors carry a status code only."""

import httpx
import pytest

from app.config import Settings
from app.llm import vault
from app.llm.base import LLMError


@pytest.fixture(autouse=True)
def _clear_cache():
    vault._cache.clear()
    yield
    vault._cache.clear()


def _settings(**over) -> Settings:
    base = {
        "azure_tenant_id": "tenant-1", "azure_client_id": "client-1",
        "azure_client_secret": "shh", "azure_vault_url": "https://example-vault.invalid",
        "azure_vault_secret_name": "my-secret",
    }
    return Settings(_env_file=None, **(base | over))


class _Transport(httpx.BaseTransport):
    """Returns canned responses for the token call then the secret call, in order."""

    def __init__(self, responses: list[httpx.Response]):
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responses.pop(0)


def _client(responses: list[httpx.Response]) -> tuple[httpx.Client, _Transport]:
    transport = _Transport(responses)
    return httpx.Client(transport=transport), transport


def _json_response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://x.invalid"))


def test_fetches_the_token_then_the_secret_and_caches_it():
    client, transport = _client(
        [
            _json_response(200, {"access_token": "tok-123"}),
            _json_response(200, {"value": "the-real-key"}),
        ]
    )
    settings = _settings()
    assert vault.fetch_secret(settings, client=client) == "the-real-key"

    token_req, secret_req = transport.requests
    assert token_req.url.host == "login.microsoftonline.com"
    assert "tenant-1" in str(token_req.url)
    assert secret_req.url.host == "example-vault.invalid"
    assert secret_req.headers["authorization"] == "Bearer tok-123"

    # A second call reuses the cache: no further requests are made, even with a broken client.
    broken = httpx.Client(transport=_Transport([]))
    assert vault.fetch_secret(settings, client=broken) == "the-real-key"


def test_different_settings_are_not_conflated_by_the_cache():
    client_a, _ = _client(
        [_json_response(200, {"access_token": "t"}), _json_response(200, {"value": "key-a"})]
    )
    client_b, _ = _client(
        [_json_response(200, {"access_token": "t"}), _json_response(200, {"value": "key-b"})]
    )
    assert vault.fetch_secret(_settings(), client=client_a) == "key-a"
    other = _settings(azure_vault_secret_name="other")
    assert vault.fetch_secret(other, client=client_b) == "key-b"


def test_a_failed_login_raises_a_status_only_error():
    body = {"error": "invalid_client", "error_description": "X"}
    client, _ = _client([_json_response(401, body)])
    with pytest.raises(LLMError) as err:
        vault.fetch_secret(_settings(), client=client)
    assert "401" in str(err.value)
    assert "invalid_client" not in str(err.value)


def test_a_failed_secret_fetch_raises_a_status_only_error():
    client, _ = _client(
        [
            _json_response(200, {"access_token": "tok"}),
            _json_response(403, {"error": {"code": "Forbidden", "message": "SECRET-DETAIL"}}),
        ]
    )
    with pytest.raises(LLMError) as err:
        vault.fetch_secret(_settings(), client=client)
    assert "403" in str(err.value)
    assert "SECRET-DETAIL" not in str(err.value)


@pytest.mark.parametrize(
    "missing", ["azure_tenant_id", "azure_client_id", "azure_vault_url", "azure_vault_secret_name"]
)
def test_a_partially_configured_vault_is_a_clear_error_before_any_call(missing):
    with pytest.raises(LLMError, match="not fully configured"):
        vault.fetch_secret(_settings(**{missing: None}))


def test_missing_client_secret_is_also_a_clear_error():
    with pytest.raises(LLMError, match="not fully configured"):
        vault.fetch_secret(_settings(azure_client_secret=None))


def test_invalidate_secret_forces_the_next_fetch_to_go_back_to_the_vault():
    settings = _settings()
    client, _ = _client(
        [_json_response(200, {"access_token": "t1"}), _json_response(200, {"value": "old-key"})]
    )
    assert vault.fetch_secret(settings, client=client) == "old-key"

    vault.invalidate_secret(settings)

    client2, _ = _client(
        [_json_response(200, {"access_token": "t2"}), _json_response(200, {"value": "new-key"})]
    )
    assert vault.fetch_secret(settings, client=client2) == "new-key"


def test_invalidate_secret_on_an_unrelated_or_uncached_key_is_a_no_op():
    settings = _settings()
    vault.invalidate_secret(settings)  # nothing cached yet - should not raise
    vault.invalidate_secret(_settings(azure_vault_secret_name="other"))
