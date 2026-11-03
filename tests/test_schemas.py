from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    Brief,
    BriefItem,
    Evaluation,
    PersonaConfig,
    ScenarioConfig,
    ScoringConfig,
    TurnOutput,
)
from tests.conftest import load_sample


def test_sample_persona_is_valid():
    persona = PersonaConfig.model_validate(load_sample("personas/ms_verma_strict.json"))
    assert persona.max_step == 4
    assert persona.version == "verma-strict-0.1"


def test_sample_scenario_is_valid():
    scenarios = load_sample("scenarios/vendor_delay.json")["scenarios"]
    scenario = ScenarioConfig.model_validate(scenarios[0])
    assert len(scenario.good_answer_contains) == 4


def test_sample_scoring_profile_is_valid():
    scoring = ScoringConfig.model_validate(load_sample("scoring/default.json"))
    assert sum(d.weight for d in scoring.dimensions) == pytest.approx(1.0)


def test_weights_must_sum_to_one():
    data = load_sample("scoring/default.json")
    data["dimensions"][0]["weight"] = 0.9
    with pytest.raises(ValidationError):
        ScoringConfig.model_validate(data)


def test_persona_ladder_steps_must_be_in_order_and_within_1_to_4():
    data = load_sample("personas/ms_verma_strict.json")
    data["escalation_ladder"].reverse()
    with pytest.raises(ValidationError):
        PersonaConfig.model_validate(data)
    data = load_sample("personas/ms_verma_strict.json")
    data["escalation_ladder"][0]["step"] = 0
    with pytest.raises(ValidationError):
        PersonaConfig.model_validate(data)


def test_persona_ignores_extra_bookkeeping_fields():
    data = load_sample("personas/ms_verma_strict.json")
    data["classification"] = "anything"
    data["internal_ref"] = "x"
    assert PersonaConfig.model_validate(data).name == "Ms. Verma"


def test_persona_turn_limits_are_checked():
    data = load_sample("personas/ms_verma_strict.json")
    data["min_turns"], data["max_turns"] = 9, 3
    with pytest.raises(ValidationError):
        PersonaConfig.model_validate(data)


def test_scenario_needs_objections_and_a_checklist():
    with pytest.raises(ValidationError):
        ScenarioConfig(
            id="X", title="t", situation="s", client_objections=[], good_answer_contains=["a"]
        )


def test_brief_item_requires_a_source_chunk():
    with pytest.raises(ValidationError):
        BriefItem(kind="claim", text="Budget is $400k", segment_ids=[])
    Brief(summary="s", items=[BriefItem(kind="claim", text="x", segment_ids=[uuid4()])])


def test_evaluation_bounds():
    with pytest.raises(ValidationError):
        Evaluation(answer_quality=1.5, quote="q", proposed_level=1)
    with pytest.raises(ValidationError):
        Evaluation(answer_quality=0.5, quote="q", proposed_level=7)
    with pytest.raises(ValidationError):
        Evaluation(answer_quality=0.5, quote="q", proposed_level=0)  # steps start at 1


def test_turn_output_roundtrip():
    out = TurnOutput(
        evaluation=Evaluation(
            answer_quality=0.2,
            checklist_met=[],
            evasive=True,
            quote="options",
            proposed_level=2,
        ),
        reply="'Options' is not a plan.",
        refs=[uuid4()],
    )
    assert TurnOutput.model_validate_json(out.model_dump_json()) == out
