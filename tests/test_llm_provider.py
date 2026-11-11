"""The real model client, tested with a stand-in for the SDK client: no network, no key."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm import LLMError, LLMRequest, Message, ProviderLLM

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")


class Reply(BaseModel):
    ok: bool
    word: str


def _settings(**over) -> Settings:
    base = {
        "llm_provider": "anthropic", "anthropic_api_key": "sk-test-not-real",
        "anthropic_model": "model-direct", "anthropic_use_azure": True,
        "anthropic_azure_endpoint": "https://example.invalid/anthropic/",
        "anthropic_azure_deployment": "deployment-x",
    }
    return Settings(_env_file=None, **(base | over))


def _request(schema=Reply) -> LLMRequest:
    return LLMRequest(
        purpose="turn", system="Be brief.", messages=[Message(role="user", content="hi")],
        response_schema=schema, temperature=0.2, max_tokens=300,
    )


def _message(text: str, stop: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
        usage=SimpleNamespace(input_tokens=11, output_tokens=7), _request_id="req_1",
    )


class StubClient:
    """Stands in for the SDK client: records the call, returns or raises what it was given."""

    def __init__(self, result=None, error: Exception | None = None, pieces=("a", "b")):
        self.calls: list[dict] = []
        self._result, self._error = result, error
        self.messages = SimpleNamespace(create=self._create, stream=self._stream)
        self._pieces = pieces

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        pieces = self._pieces

        class _Ctx:
            def __enter__(self_inner):
                return SimpleNamespace(text_stream=iter(pieces))

            def __exit__(self_inner, *exc):
                return False

        return _Ctx()


def test_sends_the_deployment_name_and_never_temperature_and_parses_the_reply():
    stub = StubClient(_message('{"ok": true, "word": "hello"}'))
    response = ProviderLLM(_settings(), client=stub).complete(_request())
    sent = stub.calls[0]
    assert sent["model"] == "deployment-x"
    assert sent["max_tokens"] == 300
    assert sent["system"] == "Be brief."
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert sent["thinking"] == {"type": "disabled"}
    assert "temperature" not in sent
    assert response.parsed == Reply(ok=True, word="hello")
    assert (response.tokens_in, response.tokens_out) == (11, 7)


def test_uses_the_plain_model_name_when_not_on_azure():
    stub = StubClient(_message('{"ok": true, "word": "x"}'))
    ProviderLLM(_settings(anthropic_use_azure=False), client=stub).complete(_request())
    assert stub.calls[0]["model"] == "model-direct"


def test_thinking_off_shape_follows_the_setting_not_a_hardcoded_default():
    """Claude Sonnet 5.5 rejects {"type": "disabled"} and needs "between_tools" instead; which
    shape is correct depends on which model the deployment points at, so it must be settable."""
    stub = StubClient(_message('{"ok": true, "word": "x"}'))
    settings = _settings(anthropic_thinking_off="between_tools")
    ProviderLLM(settings, client=stub).complete(_request())
    assert stub.calls[0]["thinking"] == {"type": "between_tools"}


def test_gateway_url_wins_over_azure_and_uses_the_plain_anthropic_client(monkeypatch):
    """An internal Anthropic-compatible gateway: plain `Anthropic(base_url=...)`, not Foundry."""
    built: dict = {}
    real_client_cls = __import__("anthropic").Anthropic

    class _Capturing(real_client_cls):
        def __init__(self, **kwargs):
            built.update(kwargs)
            super().__init__(**kwargs)
            self.messages.create = lambda **_: _message('{"ok": true, "word": "x"}')

    monkeypatch.setattr("anthropic.Anthropic", _Capturing)
    settings = _settings(
        anthropic_gateway_url="https://llmproxy.example.invalid/",
        anthropic_model="claude-sonnet-5-5-hree",
    )
    response = ProviderLLM(settings).complete(_request())
    assert built["base_url"] == "https://llmproxy.example.invalid/"
    assert built["api_key"] == "sk-test-not-real"  # passed straight through, not logged anywhere
    assert response.parsed == Reply(ok=True, word="x")


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"ok": true, "word": "x"}\n```',
        'Sure, here you go: {"ok": true, "word": "x"} Hope that helps.',
        '  {"ok": true, "word": "x"}  ',
    ],
)
def test_tolerates_a_code_fence_or_a_stray_sentence_around_the_json(text):
    response = ProviderLLM(_settings(), client=StubClient(_message(text))).complete(_request())
    assert response.parsed == Reply(ok=True, word="x")


def test_a_reply_that_does_not_match_the_schema_raises_without_leaking_the_text():
    stub = StubClient(_message("SECRET-TRAINEE-TEXT not json"))
    with pytest.raises(LLMError) as err:
        ProviderLLM(_settings(), client=stub).complete(_request())
    assert "SECRET-TRAINEE-TEXT" not in str(err.value)
    assert "Reply" in str(err.value)


def test_no_schema_returns_the_text_unparsed():
    response = ProviderLLM(_settings(), client=StubClient(_message("plain words"))).complete(
        _request(schema=None)
    )
    assert response.text == "plain words" and response.parsed is None


def test_a_refusal_and_a_cut_off_reply_are_errors():
    with pytest.raises(LLMError, match="refusal"):
        ProviderLLM(_settings(), client=StubClient(_message("", "refusal"))).complete(_request())
    with pytest.raises(LLMError, match="max_tokens"):
        ProviderLLM(_settings(), client=StubClient(_message('{"ok"', "max_tokens"))).complete(
            _request()
        )


def test_an_api_error_becomes_an_llm_error_with_the_status_only():
    response = httpx2.Response(
        429, request=httpx2.Request("POST", "https://example.invalid/"),
    )
    error = anthropic.RateLimitError(
        "ECHOED-PROMPT-TEXT", response=response,
        body={"error": {"type": "rate_limit_error", "message": "ECHOED-PROMPT-TEXT"}},
    )
    with pytest.raises(LLMError) as err:
        ProviderLLM(_settings(), client=StubClient(error=error)).complete(_request())
    assert "429" in str(err.value) and "rate_limit_error" in str(err.value)
    assert "ECHOED-PROMPT-TEXT" not in str(err.value)


def test_missing_configuration_is_a_clear_error_before_any_call():
    with pytest.raises(LLMError, match="no model key"):
        ProviderLLM(_settings(anthropic_api_key=None)).complete(_request())
    with pytest.raises(LLMError, match="Azure endpoint"):
        ProviderLLM(_settings(anthropic_azure_endpoint=None)).complete(_request())


def test_gateway_model_name_is_sent_as_is_not_the_azure_deployment():
    stub = StubClient(_message('{"ok": true, "word": "x"}'))
    settings = _settings(
        anthropic_gateway_url="https://llmproxy.example.invalid/",
        anthropic_model="claude-sonnet-5-5-hree",
    )
    ProviderLLM(settings, client=stub).complete(_request())
    assert stub.calls[0]["model"] == "claude-sonnet-5-5-hree"


def test_the_key_never_appears_in_the_settings_repr():
    assert "sk-test-not-real" not in repr(_settings())


def test_falls_back_to_the_vault_only_when_no_direct_key_is_set(monkeypatch):
    # _resolve_key() directly: a client built from the key only matters once it is used, and an
    # injected `client=` (as the other tests use) skips key resolution entirely.
    monkeypatch.setattr("app.llm.vault.fetch_secret", lambda settings: "vault-key")
    settings = _settings(anthropic_api_key=None, azure_vault_url="https://vault.invalid")
    assert ProviderLLM(settings)._resolve_key() == "vault-key"


def test_a_direct_key_wins_over_the_vault(monkeypatch):
    monkeypatch.setattr(
        "app.llm.vault.fetch_secret",
        lambda settings: (_ for _ in ()).throw(AssertionError("vault should not be called")),
    )
    settings = _settings(azure_vault_url="https://vault.invalid")  # api_key is also set
    assert ProviderLLM(settings)._resolve_key() == "sk-test-not-real"


def test_neither_key_nor_vault_is_a_clear_error():
    with pytest.raises(LLMError, match="PODC_AZURE_VAULT"):
        ProviderLLM(_settings(anthropic_api_key=None)).complete(_request())


def test_routes_through_a_local_proxy_when_one_is_set(monkeypatch):
    """A PODC_ANTHROPIC_PROXY_URL (the near end of an `ssh -D` tunnel) gets wired into the
    client's http_client, regardless of which of the three client shapes is in use."""
    built: dict = {}
    real_client_cls = __import__("anthropic").Anthropic

    class _Capturing(real_client_cls):
        def __init__(self, **kwargs):
            built.update(kwargs)
            super().__init__(**{k: v for k, v in kwargs.items() if k != "http_client"})
            self.messages.create = lambda **_: _message('{"ok": true, "word": "x"}')

    monkeypatch.setattr("anthropic.Anthropic", _Capturing)
    settings = _settings(
        anthropic_gateway_url="https://llmproxy.example.invalid/",
        anthropic_proxy_url="socks5h://127.0.0.1:1080",
    )
    ProviderLLM(settings).complete(_request())

    import anthropic

    assert isinstance(built["http_client"], anthropic.DefaultHttpxClient)


def test_no_proxy_setting_means_no_http_client_override(monkeypatch):
    built: dict = {}
    real_client_cls = __import__("anthropic").Anthropic

    class _Capturing(real_client_cls):
        def __init__(self, **kwargs):
            built.update(kwargs)
            super().__init__(**kwargs)
            self.messages.create = lambda **_: _message('{"ok": true, "word": "x"}')

    monkeypatch.setattr("anthropic.Anthropic", _Capturing)
    settings = _settings(anthropic_gateway_url="https://llmproxy.example.invalid/")
    ProviderLLM(settings).complete(_request())
    assert "http_client" not in built


def test_stream_yields_the_pieces():
    stub = StubClient(pieces=("hel", "lo"))
    assert "".join(ProviderLLM(_settings(), client=stub).stream(_request())) == "hello"
    assert stub.calls[0]["thinking"] == {"type": "disabled"}
