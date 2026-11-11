import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from app.schemas import Assessment, RoleplayResult
from app.scoring.pod_d import build_pod_d_result
from tests.conftest import load_sample


def _sample() -> dict:
    return {
        "trainee_id": "T-01",
        "C_scores": {
            "G06": 2.25,
            "G08": 3.5,
            "G10": 1.0,
        },
    }


def _assessment(weights=(0.1, 0.3, 0.4, 0.2)) -> Assessment:
    criteria = [
        {
            "id": criterion_id,
            "label": criterion_id,
            "weight": weight,
            "points": points,
            "status": status,
            "confidence": 80,
            "reason": "sample rationale",
        }
        for criterion_id, weight, points, status in zip(
            ("C1", "C2", "C3", "C4"),
            weights,
            (0.5, 0.7, 0.4, 0.2),
            ("partly", "met", "partly", "not_met"),
            strict=True,
        )
    ]
    return Assessment.model_validate(
        {
            "criteria": criteria,
            "handled": "partly",
            "confidence_score": 88,
            "human_review_required": False,
        }
    )


def test_sample_result_matches_the_pod_d_contract():
    result = RoleplayResult.model_validate(load_sample("results/vendor_delay_result.json"))

    assert result.model_dump(mode="json") == _sample()


@pytest.mark.parametrize("score", [-0.01, 5.01])
def test_goal_scores_must_be_between_zero_and_five(score):
    payload = _sample()
    payload["C_scores"]["G06"] = score

    with pytest.raises(ValidationError):
        RoleplayResult.model_validate(payload)


def test_all_pod_d_goals_are_required():
    payload = _sample()
    del payload["C_scores"]["G08"]

    with pytest.raises(ValidationError):
        RoleplayResult.model_validate(payload)


def test_internal_ref_and_unknown_goal_ids_are_rejected():
    payload = _sample()
    payload["internal_ref"] = "PR-6P5T-01"
    with pytest.raises(ValidationError):
        RoleplayResult.model_validate(payload)

    payload = _sample()
    payload["C_scores"]["G11"] = 4
    with pytest.raises(ValidationError):
        RoleplayResult.model_validate(payload)


def test_pod_d_scores_are_deterministic_weighted_mappings():
    result = build_pod_d_result(_assessment(), trainee_id="T-01")

    assert result.model_dump(mode="json") == {
        "trainee_id": "T-01",
        "C_scores": {
            "G06": pytest.approx(2.1),
            "G08": pytest.approx(3.5),
            "G10": pytest.approx(1.0),
        },
    }


def test_pod_d_mapping_requires_all_mapped_criteria():
    assessment = Assessment.model_validate(
        {
            "criteria": [
                {
                    "id": "C1",
                    "label": "Direct",
                    "weight": 1,
                    "points": 0.5,
                    "status": "partly",
                    "confidence": 80,
                    "reason": "sample rationale",
                }
            ],
            "handled": "partly",
            "confidence_score": 80,
        }
    )

    with pytest.raises(ValueError, match="missing Pod D criteria"):
        build_pod_d_result(assessment, trainee_id="T-01")


def test_generated_json_schema_matches_the_checked_in_contract():
    schema_path = Path(__file__).resolve().parents[1] / "docs" / "roleplay_result.schema.json"
    schema = RoleplayResult.model_json_schema()
    assert json.loads(schema_path.read_text(encoding="utf-8")) == schema
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(_sample())) == []
