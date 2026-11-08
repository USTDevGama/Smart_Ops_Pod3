"""Real-model checks of the known-answer cases (TDD traps C2, C3 and C4). Opt-in.

They run only when BOTH are set:
- PODC_SEED_DIR: the program's confidential seed pack, kept OUTSIDE this repo (never copy it here);
- PODC_LLM_PROVIDER: anything but "fake", that is, a real model.
Optional: PODC_EVAL_DEMAND_FILE, a local proposal-style file (PDF, DOCX or TXT), for the opening.

Why opt-in: escalation is the model's judgement now, so only a real model can show it works, and
the TDD wants those results next to the expected ones before a Stage deployment. Run with `-s` to
see the table for the Day 5 practice-run report.

What is expected comes from each case's `expected_behaviour` text. The seed's numeric
`expected_pushback_level` is deliberately not used: its scale contradicts its own examples (an
open question for the TPM). The thresholds below are starting points to tune once a real model is
connected, not facts about it.
"""

import json
import os
import re
from pathlib import Path

import pytest

from app import seed
from app.agent.engine import ContextTurn, SessionContext
from app.agent.llm_engine import LLMTurnEngine
from app.config import get_settings
from app.ingest.extract import extract_markdown
from app.llm import get_llm_client
from app.schemas.enums import FileType, TurnRole
from tests.conftest import SAMPLES

PACK = seed.seed_dir()
DEMAND_FILE = os.environ.get("PODC_EVAL_DEMAND_FILE")

pytestmark = pytest.mark.skipif(
    PACK is None or not PACK.exists() or get_settings().llm_provider == "fake",
    reason="needs PODC_SEED_DIR and a real PODC_LLM_PROVIDER",
)

LEVEL = 2  # start mid-ladder so the client can go either way


def _cases() -> list[dict]:
    if PACK is None or not PACK.exists():
        return []
    return json.loads((PACK / "sample_trainee_responses.json").read_text("utf-8"))["samples"]


def _text(relative: str) -> dict:
    return {"text": (SAMPLES / relative).read_text(encoding="utf-8")}


def _context(scenario_id: str | None = None, demand: dict | None = None) -> SessionContext:
    persona = seed.load_persona(PACK / "persona_strict.json")
    scenarios = seed.load_scenarios(PACK / "scenarios.json")
    turns = []
    if scenario_id:
        first = next(s for s in scenarios if s.id == scenario_id).client_objections[0]
        turns = [ContextTurn(role=TurnRole.PERSONA, content=first, escalation_level=LEVEL)]
    return SessionContext(
        persona=persona,
        demand=demand or _text("demand/project_demand.txt"),  # our own made-up demand
        profile=_text("profiles/sample_resume.txt"),  # our own made-up resume
        scenarios=scenarios,
        turns=turns,
        level=LEVEL,
        turns_used=0,
    )


def _engine() -> LLMTurnEngine:
    return LLMTurnEngine(get_llm_client())


def _expect(style: str, ctx: SessionContext, out) -> None:
    e, persona, reply = out.evaluation, ctx.persona, out.reply.lower()
    if style == "strong":  # pushes once at most, then accepts: no escalation
        assert not e.evasive and e.answer_quality >= persona.t_deescalate
        assert e.proposed_level <= ctx.level
    elif style == "vague":  # asks for a specific date and cost: one step tougher
        assert e.answer_quality < persona.t_escalate
        assert e.proposed_level == ctx.level + 1
    elif style == "evasive":  # deflection is flagged and escalates
        assert e.evasive
        assert e.proposed_level == ctx.level + 1
    elif style == "keyword":  # the word "budget" alone earns nothing
        assert e.answer_quality < persona.t_escalate
        assert not e.checklist_met
        assert e.proposed_level > ctx.level
    elif style == "override":  # stays in character, never says it went well
        assert e.answer_quality < persona.t_escalate
        assert e.proposed_level >= ctx.level
        assert "went well" not in reply and "passed" not in reply
    else:
        pytest.fail(f"unknown style {style!r}")


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["id"])
def test_known_answer_case(case):
    ctx = _context(case["scenario_id"])
    out = _engine().respond(ctx, case["trainee_message"])
    e = out.evaluation
    print(
        f"\n{case['id']:<12} quality={e.answer_quality:.2f} evasive={e.evasive} "
        f"level {ctx.level}->{e.proposed_level} met={len(e.checklist_met)}\n"
        f"  expected: {case['expected_behaviour']}\n  reply:    {out.reply}"
    )
    assert e.quote in case["trainee_message"]
    _expect(case["style"], ctx, out)


@pytest.mark.skipif(not DEMAND_FILE, reason="PODC_EVAL_DEMAND_FILE not set")
def test_the_opening_is_built_on_facts_from_the_demand_document():
    path = Path(DEMAND_FILE)
    markdown = extract_markdown(path.read_bytes(), FileType(path.suffix.lstrip(".").lower()))
    ctx = _context(demand={"text": markdown})
    out = _engine().opening(ctx)
    print(f"\nopening: {out.reply}")

    def words(text: str) -> set[str]:
        return set(re.findall(r"[a-z]{5,}", text.lower()))

    assert out.evaluation.proposed_level == 1
    assert len(words(out.reply) & words(markdown)) >= 2  # grounded, not generic
