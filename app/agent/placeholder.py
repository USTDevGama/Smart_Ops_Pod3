"""TEMPORARY engine with no LLM: canned, deterministic logic so the endpoints and tests work.

The real engine (prompting, escalation, evaluation) is the agent owner's work and replaces this
through `get_engine()` in app/agent/engine.py.
"""

import re

from app.agent.engine import SessionContext
from app.schemas import Evaluation, TurnOutput


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$%]+", text.lower()) if len(w) >= 5}


def _quality(answer: str) -> float:
    has_figure = bool(re.search(r"\d", answer))
    long_enough = len(answer.split()) >= 12
    return 0.85 if has_figure and long_enough else 0.3


class PlaceholderEngine:
    def opening(self, ctx: SessionContext) -> TurnOutput:
        return TurnOutput(
            evaluation=Evaluation(answer_quality=1.0, quote="-", proposed_level=1),
            reply=ctx.scenario.client_objections[0],
            refs=self._refs(ctx),
        )

    def respond(self, ctx: SessionContext, answer: str) -> TurnOutput:
        quality = _quality(answer)
        met = [
            item
            for item in ctx.open_checklist
            if (w := _words(item)) and len(w & _words(answer)) * 2 >= len(w)
        ]
        level = ctx.level + 1 if quality < ctx.persona.t_escalate else max(1, ctx.level - 1)
        objections = ctx.scenario.client_objections
        reply = objections[(ctx.turns_used + 1) % len(objections)]
        if quality < ctx.persona.t_escalate:
            reply = f"That is not specific enough. {reply}"
        return TurnOutput(
            evaluation=Evaluation(
                answer_quality=quality,
                checklist_met=met,
                evasive=quality < ctx.persona.t_escalate,
                quote=answer.strip()[:80],
                proposed_level=min(max(level, 1), 4),
            ),
            reply=reply,
            refs=self._refs(ctx),
        )

    @staticmethod
    def _refs(ctx: SessionContext) -> list:
        if ctx.brief is None or not ctx.brief.items:
            return []
        return [ctx.brief.items[0].segment_ids[0]]
