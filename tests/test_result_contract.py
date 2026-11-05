"""The program's result format ("roleplay-result") that leaves the pod."""

import copy

import jsonschema
import pytest
from pydantic import ValidationError

from app.schemas import RoleplayResult


def _sample() -> dict:
    return {
        "session_id": "sess-sample",
        "scenario_id": "VD-01",
        "persona_version": "verma-strict-0.1",
        "turns": [
            {"turn": 1, "role": "client", "text": "Why was delivery late?"},
            {"turn": 2, "role": "trainee", "text": "I own the delay."},
        ],
        "result": {
            "pushback_peak_step": 2,
            "handled": "partly",
            "strengths": ["Accepted responsibility"],
            "gaps": ["No prevention plan"],
            "evidence_turns": [2],
        },
    }


def test_sample_result_is_valid():
    result = RoleplayResult.model_validate(_sample())
    assert result.human_review_required is True
    assert result.result.evidence_turns == [2]


def test_evidence_must_point_at_a_real_turn():
    doc = _sample()
    doc["result"]["evidence_turns"] = [99]
    with pytest.raises(ValidationError, match="do not exist"):
        RoleplayResult.model_validate(doc)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["result"].update(handled="maybe"),
        lambda d: d["result"].update(pushback_peak_step=9),
        lambda d: d["result"].update(pushback_peak_step="banana"),
        lambda d: d.update(turns="not a list"),
        lambda d: d["turns"][0].update(role="persona"),  # the contract says "client"
        lambda d: d["result"].pop("gaps"),
        lambda d: d.pop("persona_version"),
    ],
)
def test_garbage_is_rejected(change):
    doc = copy.deepcopy(_sample())
    change(doc)
    with pytest.raises(ValidationError):
        RoleplayResult.model_validate(doc)


def test_generated_json_schema_agrees_with_the_model():
    """docs/roleplay_result.schema.json is generated from the model; outsiders can use it."""
    schema = RoleplayResult.model_json_schema()
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(_sample())) == []

    bad = _sample()
    bad["result"]["handled"] = 12345
    bad["turns"] = "not a list"
    assert list(validator.iter_errors(bad)) != []  # the program's own schema let this through
