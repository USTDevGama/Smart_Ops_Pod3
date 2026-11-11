"""The real turn engine: ONE model call per turn, then plain checks.

    respond(ctx, answer)
      1. settle the scenario   context.py   from what the service saved, else the model says which
      2. build the prompt      prompts.py   rules + persona in `system`, everything else as data
      3. ONE model call        LLMClient    judges the answer AND writes the client's next message
      4. check the result      validate.py  quote is in the answer, checklist, level range, reply
      5. return TurnOutput     the service clamps the level, saves, counts turns and ends the chat

The model decides how tough to be (`proposed_level`); the service enforces the one-step limit.
This engine only checks that the proposal is in the range the service will keep, so the tone of the
reply and the level saved with it agree.

A normal turn costs one call. There is exactly one retry, only when the result is unusable (a quote
that is not in the answer, a level out of range, a reply that is not text, a reply that does not
match the schema, or a failed call). After that, or if the model is too slow, `AgentError` is
raised: the service answers 502 and saves nothing, so the trainee keeps their turn.

Errors and logs carry reason codes only, never the conversation, a document or the model's text.
"""

import logging
import threading
import time
from collections.abc import Callable

from pydantic import BaseModel

from app.agent import prompts
from app.agent.context import find_scenario, legal_levels, met_items, settled_scenario
from app.agent.drafts import OpeningDraft, TurnDraft
from app.agent.engine import SessionContext
from app.agent.errors import AgentError, MalformedReply
from app.agent.validate import check_level, map_checklist, snap_quote, tidy_reply, unit
from app.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse, Message
from app.schemas import Evaluation, TurnOutput

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 25.0  # one model call
DEFAULT_DEADLINE_S = 35.0  # the whole turn, including the one retry
MIN_ATTEMPT_S = 3.0  # not worth starting an attempt with less time than this


class _Timeout(Exception):
    pass


def _with_timeout(call: Callable[[], LLMResponse], seconds: float) -> LLMResponse:
    """Run a model call, giving up after `seconds`.

    The model client has no timeout of its own yet (`LLMRequest` carries none), so the wait is
    bounded here. A call that gives up keeps running in its daemon thread until the client
    returns, but nobody waits for it. Once `LLMRequest` gets a timeout, the client should enforce
    it and this guard becomes a safety net.
    """
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = call()
        except Exception as exc:  # re-raised in the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=run, name="agent-llm-call", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise _Timeout
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


class LLMTurnEngine:
    def __init__(
        self,
        llm: LLMClient,
        *,
        temperature: float = 0.2,
        max_tokens: int = 600,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        deadline_s: float = DEFAULT_DEADLINE_S,
    ):
        self._llm = llm
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s
        self._deadline_s = deadline_s

    # --- the two things the chat service asks for ---------------------------------------------

    def opening(self, ctx: SessionContext) -> TurnOutput:
        if not ctx.scenarios:
            raise AgentError("there are no scenarios to choose from")
        system = prompts.system_prompt(ctx.persona)
        user = prompts.opening_message(ctx)

        def check(draft: OpeningDraft) -> TurnOutput:
            scenario = find_scenario(ctx.scenarios, draft.scenario_id)
            if scenario is None:
                raise MalformedReply("unknown_scenario")
            log.info("agent opening chose scenario %s", scenario.id)
            return TurnOutput(
                # The opening has no answer to judge; the service ignores this evaluation and
                # saves the opening at level 1.
                evaluation=Evaluation(answer_quality=1.0, quote="-", proposed_level=1),
                reply=tidy_reply(draft.reply, ctx.persona.name),
            )

        return self._run("opening", system, user, OpeningDraft, check)

    def respond(self, ctx: SessionContext, answer: str) -> TurnOutput:
        if not ctx.scenarios:
            raise AgentError("there are no scenarios to choose from")
        system = prompts.system_prompt(ctx.persona)
        low, high = legal_levels(ctx)
        settled = settled_scenario(ctx)
        user = prompts.turn_message(ctx, answer, settled, low, high)

        def check(draft: TurnDraft) -> TurnOutput:
            scenario = settled or find_scenario(ctx.scenarios, draft.scenario_id)
            if scenario is None:
                raise MalformedReply("unknown_scenario")
            quote = snap_quote(answer, draft.quote)
            if quote is None:  # never invent evidence: the words must be the trainee's own
                raise MalformedReply("quote_not_in_answer")
            level = check_level(draft.proposed_level, low, high)
            return TurnOutput(
                evaluation=Evaluation(
                    answer_quality=unit(draft.answer_quality),
                    checklist_met=map_checklist(
                        draft.checklist_met, scenario.good_answer_contains, met_items(ctx)
                    ),
                    evasive=draft.evasive,
                    composure=unit(draft.composure),
                    quote=quote,
                    proposed_level=level,
                ),
                reply=tidy_reply(draft.reply, ctx.persona.name),
            )

        return self._run("turn", system, user, TurnDraft, check)

    # --- helpers --------------------------------------------------------------------------------

    def _run[D: BaseModel](
        self,
        purpose: str,
        system: str,
        user: str,
        schema: type[D],
        check: Callable[[D], TurnOutput],
    ) -> TurnOutput:
        """One attempt, and one retry if the result is unusable. Anything else raises."""
        started = time.monotonic()
        code = ""
        for attempt in (1, 2):
            remaining = self._deadline_s - (time.monotonic() - started)
            if remaining < MIN_ATTEMPT_S:
                raise AgentError("the turn ran out of time")
            message = user if attempt == 1 else user + prompts.retry_note(code)
            timeout = min(self._timeout_s, remaining)
            try:
                result = check(self._call(purpose, system, message, schema, timeout))
            except MalformedReply as bad:
                code = bad.code
            except _Timeout:
                log.warning("agent %s timed out (attempt %d)", purpose, attempt)
                raise AgentError("the model call timed out") from None
            except LLMError as failure:
                # The client raises LLMError for a failed call and for a schema mismatch alike, so
                # they cannot be told apart yet. One retry is cheap for the second, and the
                # deadline bounds the first.
                code = "schema"
                # The message is a reason code only (HTTP status, vault step, schema name), never
                # the prompt or the model's text, so it is safe to log. It is what tells a 403
                # from a reply that did not parse.
                log.warning("agent %s attempt %d: %s", purpose, attempt, failure)
            else:
                elapsed = time.monotonic() - started
                log.info("agent %s ok (attempt %d, %.1fs)", purpose, attempt, elapsed)
                return result
            log.warning("agent %s attempt %d rejected: %s", purpose, attempt, code)
        raise AgentError(f"the model's reply could not be used ({code})")

    def _call[D: BaseModel](
        self, purpose: str, system: str, user: str, schema: type[D], timeout: float
    ) -> D:
        request = LLMRequest(
            purpose=purpose,
            system=system,
            messages=[Message(role="user", content=user)],
            response_schema=schema,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        response = _with_timeout(lambda: self._llm.complete(request), timeout)
        if not isinstance(response.parsed, schema):
            raise MalformedReply("schema")
        log.info(
            "agent %s call tokens_in=%s tokens_out=%s",
            purpose, response.tokens_in, response.tokens_out,
        )
        return response.parsed
