"""The hard rules around the agent. Pure functions: no database, no model."""

from app.schemas import PersonaConfig


def clamp_level(previous: int, proposed: int, max_step: int) -> int:
    """The client moves at most one step at a time, and always stays within 1..max_step."""
    stepped = max(previous - 1, min(previous + 1, proposed))
    return max(1, min(max_step, stepped))


def allowed_turns(persona: PersonaConfig, qualities: list[float]) -> int:
    """`max_turns`, plus `grace_turns` only while the trainee's answers are getting better."""
    improving = len(qualities) >= 2 and qualities[-1] > qualities[-2]
    return persona.max_turns + (persona.grace_turns if improving else 0)
