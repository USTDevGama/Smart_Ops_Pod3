"""TEMPORARY engine with no LLM: canned, deterministic logic so the endpoints and tests work.

The real engine (prompting, escalation, evaluation) is the agent owner's work and replaces this
through `get_engine()` in app/agent/engine.py.
"""

import re

from app.agent.engine import SessionContext
from app.schemas import Evaluation, TurnOutput


def _quality(answer: str) -> float:
    has_figure = bool(re.search(r"\d", answer))
    long_enough = len(answer.split()) >= 12
    return 0.85 if has_figure and long_enough else 0.3


def _objections(ctx: SessionContext) -> list[str]:
    """Every objection of every scenario, in order (the real agent chooses with judgement)."""
    found = [o for s in ctx.scenarios for o in s.client_objections]
    return found or ["Walk me through how you would handle that."]


class PlaceholderEngine:
    def opening(self, ctx: SessionContext) -> TurnOutput:
        return TurnOutput(
            evaluation=Evaluation(answer_quality=1.0, quote="-", proposed_level=1),
            reply=_objections(ctx)[0],
            refs=self._refs(ctx),
        )

    def respond(self, ctx: SessionContext, answer: str) -> TurnOutput:
        quality = _quality(answer)
        level = ctx.level + 1 if quality < ctx.persona.t_escalate else max(1, ctx.level - 1)
        objections = _objections(ctx)
        reply = objections[(ctx.turns_used + 1) % len(objections)]
        if quality < ctx.persona.t_escalate:
            reply = f"That is not specific enough. {reply}"
        return TurnOutput(
            evaluation=Evaluation(
                answer_quality=quality,
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
