"""LLM Gateway (owner: Dev D)."""

from app.config import Settings, get_settings
from app.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse, Message
from app.llm.fake import FakeLLM
from app.llm.provider import ProviderLLM


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    if settings.llm_provider == "fake":
        return FakeLLM(strict=False)
    return ProviderLLM(settings)


__all__ = [
    "FakeLLM",
    "LLMClient",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "Message",
    "ProviderLLM",
    "get_llm_client",
]
