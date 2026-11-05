"""The real turn engine: one model call per turn, then plain code takes over.

    respond(ctx, answer)
      1. build the prompt      prompts.py     trusted rules in `system`, untrusted text in `user`
      2. ONE model call        LLMClient      judges the answer AND writes the reply
      3. check the result      grounding.py   the quote is in the answer; numbers, labels are real
      4. decide the level      escalation.py  code, never the model
      5. if the reply was written at a different level than the code chose: ONE rewrite call
      6. return TurnOutput     the chat service saves it and enforces the hard limits

A normal turn costs one model call. A second one happens only when the quote was wrong (a repair)
or the reply's tone does not match the level the rules chose (a rewrite). Any failure raises
`AgentError`; the chat service answers 502 and saves nothing, so the trainee keeps their turn.
"""

import re

from pydantic import BaseModel

from app.agent import prompts
from app.agent.drafts import ReplyDraft, TurnDraft
from app.agent.engine import SessionContext
from app.agent.errors import AgentError
from app.agent.escalation import last_trainee_evaluation, next_level
from app.agent.grounding import map_checklist, map_cites, neutralize, snap_quote
from app.llm.base import LLMClient, LLMError, LLMRequest, Message
from app.schemas import Evaluation, TurnOutput

MAX_REPLY_CHARS = 1200
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class LLMTurnEngine:
    def __init__(self, llm: LLMClient, *, temperature: float = 0.2, max_tokens: int = 700):
        self._llm = llm
        self._temperature = temperature
        self._max_tokens = max_tokens

    # --- the two things the chat service asks for ---------------------------------------------

    def opening(self, ctx: SessionContext) -> TurnOutput:
        system = prompts.system_prompt(ctx.persona, ctx.scenario)
        draft = self._ask("opening", system, prompts.opening_message(ctx), ReplyDraft)
        return TurnOutput(
            # The opening has no answer to judge; the service ignores this evaluation.
            evaluation=Evaluation(answer_quality=1.0, quote="-", proposed_level=1),
            reply=self._reply(draft.reply, ctx),
            refs=map_cites(draft.cites, prompts.brief_labels(ctx.brief)),
        )

    def respond(self, ctx: SessionContext, answer: str) -> TurnOutput:
        system = prompts.system_prompt(ctx.persona, ctx.scenario)
        user = prompts.turn_message(ctx, answer)

        draft = self._ask("turn", system, user, TurnDraft)
        quote = snap_quote(answer, draft.quote)
        if quote is None:  # the model cited words the trainee never wrote: one repair attempt
            draft = self._ask("turn", system, user + prompts.QUOTE_REPAIR, TurnDraft)
            quote = snap_quote(answer, draft.quote)
        if quote is None:
            raise AgentError("the model's quote is not in the trainee's answer")

        judgement = dict(
            answer_quality=_unit(draft.answer_quality),
            checklist_met=map_checklist(draft.checklist_met, ctx.open_checklist),
            evasive=draft.evasive,
            composure=_unit(draft.composure),
            quote=quote,
        )
        level = next_level(
            ctx.persona,
            ctx.level,
            Evaluation(**judgement, proposed_level=ctx.level),
            last_trainee_evaluation(ctx.turns),
        )

        reply, cites = draft.reply, draft.cites
        written_at = max(1, min(ctx.persona.max_step, draft.proposed_level))
        if written_at != level:  # the wording does not match the level the rules chose
            rewrite = self._ask(
                "turn_reply", system, prompts.rewrite_message(ctx, answer, level), ReplyDraft
            )
            reply, cites = rewrite.reply, rewrite.cites

        return TurnOutput(
            evaluation=Evaluation(**judgement, proposed_level=level),
            reply=self._reply(reply, ctx),
            refs=map_cites(cites, prompts.brief_labels(ctx.brief)),
        )

    # --- helpers --------------------------------------------------------------------------------

    def _ask[D: BaseModel](self, purpose: str, system: str, user: str, schema: type[D]) -> D:
        request = LLMRequest(
            purpose=purpose,
            system=system,
            messages=[Message(role="user", content=user)],
            response_schema=schema,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        try:
            parsed = self._llm.complete(request).parsed
        except LLMError as exc:
            raise AgentError(f"the model call failed ({purpose})") from exc
        if not isinstance(parsed, schema):
            raise AgentError(f"the model reply was not in the expected shape ({purpose})")
        return parsed

    @staticmethod
    def _reply(text: str, ctx: SessionContext) -> str:
        """Tidy the client's line: no wrapper tags, no 'Name:' label, a sane length."""
        text = neutralize(text).strip()
        text = re.sub(rf"^(?:client|{re.escape(ctx.persona.name)})\s*:\s*", "", text, flags=re.I)
        text = " ".join(text.split())
        if not text:
            raise AgentError("the model returned an empty reply")
        if len(text) > MAX_REPLY_CHARS:
            cut = text[:MAX_REPLY_CHARS]
            ends = [m.end() for m in _SENTENCE_END.finditer(cut)]
            text = cut[: ends[-1]] if ends else cut.rstrip()
        return text
