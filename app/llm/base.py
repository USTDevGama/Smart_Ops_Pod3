"""The only way the rest of the code talks to a language model.

Everything (ingest, agent, scoring) codes against `LLMClient`, so it can be tested with
`FakeLLM` and switched to a real provider when the API keys arrive.
"""

from collections.abc import Iterator
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class LLMError(Exception):
    """Raised when a call fails or returns output that does not match the requested schema."""


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    purpose: str  # brief | opening | turn | score
    system: str
    messages: list[Message] = Field(default_factory=list)
    response_schema: type[BaseModel] | None = None  # parse and validate the reply as JSON
    temperature: float = 0.0
    max_tokens: int = 1024


class LLMResponse(BaseModel):
    text: str
    parsed: BaseModel | None = None
    tokens_in: int = 0
    tokens_out: int = 0


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...

    def stream(self, request: LLMRequest) -> Iterator[str]: ...
