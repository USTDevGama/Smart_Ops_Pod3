"""The real model client: Claude, direct, through Azure AI Foundry, or through an internal
Anthropic-compatible gateway.

Everything else codes against `LLMClient`, so this is the only place that knows about the
provider. Settings (`PODC_ANTHROPIC_*`) come from `app/config.py`; the key is a `SecretStr`.
If no key is set directly, it is fetched from Azure Key Vault instead (`app/llm/vault.py`,
`PODC_AZURE_*`) - a direct key always wins. The vault's fetch is cached, so a rotated secret
isn't refetched until a call made with the stale key is rejected as unauthorized; at that point
the cache is dropped and the call is retried once with a freshly fetched key. If this machine
cannot reach the model directly,
`PODC_ANTHROPIC_PROXY_URL` routes the call through a local SOCKS/HTTP proxy instead (typically
an `ssh -D` tunnel to a host that can reach it).

Choices that are easy to get wrong:
  * `request.temperature` is NOT sent. The current Claude models reject sampling parameters.
  * `thinking` is sent as off. The agent asks for a short JSON reply under a tight timeout, and
    hidden reasoning would eat `max_tokens` and the wait. Which shape means "off" is model-
    generation-specific: most Claude models accept `{"type": "disabled"}`, but Claude Sonnet 5.5
    rejects it and needs `{"type": "between_tools"}` instead - set `PODC_ANTHROPIC_THINKING_OFF`
    to match whatever model the deployment actually points at.
  * Errors and logs carry reason codes only (HTTP status, error type, schema name), never the
    prompt or the model's text (BR-13).
"""

import logging
import re
import time
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.llm.base import LLMError, LLMRequest, LLMResponse

log = logging.getLogger(__name__)

MAX_RETRIES = 1  # the SDK retries 408/409/429/5xx and connection errors; the callers retry too
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class ProviderLLM:
    def __init__(self, settings: Settings | None = None, client: Any | None = None):
        self._settings = settings or get_settings()
        self._client = client  # tests pass a stand-in; otherwise built on first use

    # --- LLMClient ------------------------------------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        client = self._get_client()
        message = self._create(client, request)

        if message.stop_reason == "refusal":
            raise LLMError("the model declined the request (refusal)")
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        if request.response_schema is not None and message.stop_reason == "max_tokens":
            raise LLMError("the reply was cut off (max_tokens)")

        usage = message.usage
        log.info(
            "llm call purpose=%s model=%s tokens_in=%s tokens_out=%s %.1fs request_id=%s",
            request.purpose, self._model(), usage.input_tokens, usage.output_tokens,
            time.monotonic() - started, getattr(message, "_request_id", None),
        )
        return LLMResponse(
            text=text,
            parsed=_parse(text, request.response_schema),
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
        )

    def stream(self, request: LLMRequest) -> Iterator[str]:
        import anthropic

        client = self._get_client()
        try:
            with client.messages.stream(**self._kwargs(request)) as stream:
                yield from stream.text_stream
        except anthropic.AuthenticationError:
            client = self._refresh_client()
            try:
                with client.messages.stream(**self._kwargs(request)) as stream:
                    yield from stream.text_stream
            except anthropic.APIError as exc:
                raise _call_failed(exc) from None
        except anthropic.APIError as exc:
            raise _call_failed(exc) from None

    # --- helpers --------------------------------------------------------------------------------

    def _model(self) -> str:
        s = self._settings
        if s.anthropic_gateway_url:  # the gateway's own model/deployment id
            return s.anthropic_model
        if s.anthropic_use_azure and s.anthropic_azure_deployment:
            return s.anthropic_azure_deployment
        return s.anthropic_model

    def _kwargs(self, request: LLMRequest) -> dict[str, Any]:
        return {
            "model": self._model(),
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "thinking": {"type": self._settings.anthropic_thinking_off},
        }

    def _create(self, client: Any, request: LLMRequest) -> Any:
        import anthropic

        try:
            return client.messages.create(**self._kwargs(request))
        except anthropic.AuthenticationError:
            client = self._refresh_client()
            try:
                return client.messages.create(**self._kwargs(request))
            except anthropic.APIError as exc:
                raise _call_failed(exc) from None
        except anthropic.APIError as exc:
            raise _call_failed(exc) from None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        s = self._settings
        key = self._resolve_key()
        import anthropic

        # When this machine cannot reach the model directly (e.g. a network-proxy block), route
        # through a local SOCKS/HTTP proxy instead - typically the near end of an `ssh -D` tunnel
        # to a host that can reach it. Built the same way regardless of which client class below
        # ends up using it.
        extra: dict[str, Any] = {}
        if s.anthropic_proxy_url:
            extra["http_client"] = anthropic.DefaultHttpxClient(proxy=s.anthropic_proxy_url)

        if s.anthropic_gateway_url:
            # An internal reverse proxy speaking the plain Anthropic /v1/messages shape: the
            # vanilla client with its base_url overridden, not the Azure-Foundry-specific class.
            self._client = anthropic.Anthropic(
                base_url=s.anthropic_gateway_url, api_key=key,
                timeout=s.anthropic_timeout_s, max_retries=MAX_RETRIES, **extra,
            )
        elif s.anthropic_use_azure:
            if not s.anthropic_azure_endpoint:
                raise LLMError("no Azure endpoint is set (PODC_ANTHROPIC_AZURE_ENDPOINT)")
            self._client = anthropic.AnthropicFoundry(
                base_url=s.anthropic_azure_endpoint, api_key=key,
                timeout=s.anthropic_timeout_s, max_retries=MAX_RETRIES, **extra,
            )
        else:
            self._client = anthropic.Anthropic(
                api_key=key, timeout=s.anthropic_timeout_s, max_retries=MAX_RETRIES, **extra
            )
        return self._client

    def _refresh_client(self) -> Any:
        """Called after an `AuthenticationError`: the cached key is stale, most likely a Key
        Vault secret that got rotated under us. Drop the vault's cached value (if that's where
        the key came from) and the built client, then rebuild from a fresh fetch."""
        s = self._settings
        if s.anthropic_api_key is None and s.azure_vault_url:
            from app.llm.vault import invalidate_secret

            invalidate_secret(s)
        self._client = None
        return self._get_client()

    def _resolve_key(self) -> str:
        """A direct key always wins; otherwise fall back to the Key Vault secret (if the vault
        settings look configured at all - a partial vault config raises its own clear error)."""
        s = self._settings
        if s.anthropic_api_key is not None:
            return s.anthropic_api_key.get_secret_value()
        if s.azure_vault_url:
            from app.llm.vault import fetch_secret

            return fetch_secret(s)
        raise LLMError(
            "no model key is configured (set PODC_ANTHROPIC_API_KEY, or the PODC_AZURE_VAULT_* "
            "settings)"
        )


def _call_failed(exc: Exception) -> LLMError:
    """A reason code only: the status and the error type, never the server's message."""
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    kind = body.get("error", {}).get("type") if isinstance(body, dict) else None
    detail = f"HTTP {status}" if status else type(exc).__name__
    return LLMError(f"the model call failed ({detail}{f', {kind}' if kind else ''})")


def _parse(text: str, schema: type[BaseModel] | None) -> BaseModel | None:
    if schema is None:
        return None
    try:
        return schema.model_validate_json(_json_body(text))
    except ValidationError:
        raise LLMError(f"reply does not match {schema.__name__}") from None


def _json_body(text: str) -> str:
    """The JSON object in a reply, tolerating a code fence or a stray sentence around it."""
    body = _FENCE.sub("", text.strip()).strip()
    if not body.startswith("{") and "{" in body and "}" in body:
        body = body[body.index("{") : body.rindex("}") + 1]
    return body
