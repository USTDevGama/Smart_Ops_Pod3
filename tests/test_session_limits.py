from pathlib import Path

import pytest

from app.agent.engine import SessionContext
from app.agent.placeholder import PlaceholderEngine
from app.schemas import PersonaConfig, ScenarioConfig
from app.sessions.limits import allowed_turns, clamp_level
from tests.conftest import ROOT, load_sample


@pytest.mark.parametrize(
    ("previous", "proposed", "max_step", "expected"),
    [(1, 4, 4, 2), (3, 1, 4, 2), (2, 2, 4, 2), (4, 4, 4, 4), (1, 1, 4, 1), (3, 4, 3, 3)],
)
def test_the_level_moves_one_step_and_stays_in_range(previous, proposed, max_step, expected):
    assert clamp_level(previous, proposed, max_step) == expected


def _persona(**extra) -> PersonaConfig:
    return PersonaConfig.model_validate(load_sample("personas/ms_verma_strict.json") | extra)


def test_grace_turns_only_count_while_answers_improve():
    persona = _persona(max_turns=6, grace_turns=2)
    assert allowed_turns(persona, [0.3, 0.6]) == 8
    assert allowed_turns(persona, [0.6, 0.3]) == 6
    assert allowed_turns(persona, [0.6]) == 6
    assert allowed_turns(_persona(max_turns=6), [0.3, 0.9]) == 6


def _ctx(level=1, open_checklist=None) -> SessionContext:
    raw = load_sample("scenarios/vendor_delay.json")["scenarios"][0]
    scenario = ScenarioConfig.model_validate(raw)
    return SessionContext(
        persona=_persona(), scenario=scenario, level=level,
        open_checklist=open_checklist or scenario.good_answer_contains,
    )


def test_placeholder_engine_gets_tougher_on_vague_answers_and_easier_on_specific_ones():
    engine = PlaceholderEngine()
    vague = engine.respond(_ctx(level=2), "We are looking at options.")
    assert vague.evaluation.proposed_level == 3
    assert vague.reply.startswith("That is not specific enough.")
    specific = engine.respond(
        _ctx(level=2),
        "The supplier now commits to 9 June, and we will cover the 12 000 cost of the delay.",
    )
    assert specific.evaluation.proposed_level == 1


def test_placeholder_quote_is_really_in_the_answer():
    answer = "  The supplier now commits to 9 June  "
    out = PlaceholderEngine().respond(_ctx(), answer)
    assert out.evaluation.quote in answer


def test_the_chat_service_does_not_depend_on_an_agent_framework():
    """Keeps the LangGraph-or-plain-prompt choice open for the agent owner."""
    for folder in ("sessions", "api", "ingest"):
        for path in Path(ROOT / "app" / folder).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "langgraph" not in source
            assert "langchain" not in source
