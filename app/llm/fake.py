import json
from collections.abc import Iterator

from pydantic import BaseModel, ValidationError

from app.llm.base import LLMError, LLMRequest, LLMResponse

Scripted = str | dict | BaseModel


class FakeLLM:
    """Scripted stand-in for a real model: no network, no key, fully repeatable.

    `script` maps a request purpose to the replies to hand out, in order:

        FakeLLM({"turn": [TurnOutput(...), TurnOutput(...)], "score": [ScoringOutput(...)]})

    Every request is recorded in `.calls` so tests can assert on what the code sent.
    """

    def __init__(self, script: dict[str, list[Scripted]] | None = None, strict: bool = True):
        self._script = {purpose: list(items) for purpose, items in (script or {}).items()}
        self._strict = strict
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        queue = self._script.get(request.purpose)
        if queue:
            text = self._to_text(queue.pop(0))
        elif self._strict:
            raise LLMError(f"FakeLLM has no scripted reply left for purpose={request.purpose!r}")
        else:
            text = "[fake reply]"

        parsed = None
        if request.response_schema is not None:
            try:
                parsed = request.response_schema.model_validate_json(text)
            except ValidationError as exc:
                raise LLMError(f"reply does not match {request.response_schema.__name__}") from exc

        prompt_chars = len(request.system) + sum(len(m.content) for m in request.messages)
        return LLMResponse(
            text=text, parsed=parsed, tokens_in=prompt_chars // 4, tokens_out=len(text) // 4
        )

    def stream(self, request: LLMRequest) -> Iterator[str]:
        for word in self.complete(request).text.split(" "):
            yield word + " "

    @staticmethod
    def _to_text(item: Scripted) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, BaseModel):
            return item.model_dump_json()
        return json.dumps(item)
