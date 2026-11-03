from collections.abc import Iterator

from app.llm.base import LLMRequest, LLMResponse


class ProviderLLM:
    """Real provider client. Not written yet: waiting on the provider, models and API keys.

    Implement `complete` and `stream` here (retries, timeouts, JSON validation, a row in
    `llm_call_log` per call). Nothing else in the code base should need to change.
    """

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError("No LLM provider configured yet (set up when API keys arrive)")

    def stream(self, request: LLMRequest) -> Iterator[str]:
        raise NotImplementedError("No LLM provider configured yet (set up when API keys arrive)")
