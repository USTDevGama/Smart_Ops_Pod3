"""How tough the client is. Plain code decides this, never the model.

The model only judges an answer (a number between 0 and 1) and writes the wording. The rules below
turn that judgement into a level, so the same answer always gives the same level, and a trainee
cannot talk the client into easing off. The chat service (app/sessions/limits.py) then enforces
one more hard limit around this: never more than one step from the previous level.

    answer is weak   (evasive, or quality < t_escalate)            -> one step tougher
    answer is strong (not evasive, quality >= t_deescalate) twice
                     in a row                                      -> one step easier
    anything else                                                  -> stay where we are
"""

from app.agent.engine import ContextTurn
from app.schemas import Evaluation, PersonaConfig
from app.schemas.enums import TurnRole


def is_weak(answer: Evaluation, persona: PersonaConfig) -> bool:
    return answer.evasive or answer.answer_quality < persona.t_escalate


def is_strong(answer: Evaluation, persona: PersonaConfig) -> bool:
    return not answer.evasive and answer.answer_quality >= persona.t_deescalate


def next_level(
    persona: PersonaConfig, level: int, latest: Evaluation, previous: Evaluation | None
) -> int:
    """The client's level for its reply.

    `latest` judges the answer just given. `previous` judges the trainee's answer before it (None
    on the first answer): one good answer is not enough to ease off, two in a row are.
    """
    level = max(1, min(level, persona.max_step))
    if is_weak(latest, persona):
        return min(level + 1, persona.max_step)
    if previous is not None and is_strong(latest, persona) and is_strong(previous, persona):
        return max(level - 1, 1)
    return level


def last_trainee_evaluation(turns: list[ContextTurn]) -> Evaluation | None:
    """The judgement of the trainee's most recent answer so far (None before the first)."""
    for turn in reversed(turns):
        if turn.role == TurnRole.TRAINEE and turn.evaluation is not None:
            return turn.evaluation
    return None


def move_for(persona: PersonaConfig, level: int) -> str:
    """What the client does at `level`: the ladder rung at that step (or the nearest one below)."""
    ladder = sorted(persona.escalation_ladder, key=lambda step: step.step)
    chosen = ladder[0]
    for step in ladder:
        if step.step <= level:
            chosen = step
    return chosen.move
