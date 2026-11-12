import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import Assessment, RoleplayResult
from app.scoring.pod_d import build_pod_d_result
from tests.conftest import load_sample


def _sample() -> dict:
    return {
        "trainee_id": "T-01",
        "C_scores": {
            "G06": 2,
            "G08": 4,
            "G10": 1,
        },
    }


def _assessment(
    points=(0.5, 0.7, 0.4, 0.2),
    weights=(0.25, 0.3, 0.25, 0.2),
) -> Assessment:
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
            points,
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


@pytest.mark.parametrize("score", [0, 6, 2.5])
def test_goal_scores_must_be_integers_between_one_and_five(score):
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

    assert result.model_dump(mode="json") == _sample()


def test_scores_round_half_up_and_zero_is_clamped_to_database_minimum():
    assessment = _assessment(points=(0.0, 0.0, 0.0, 0.0))

    result = build_pod_d_result(assessment, trainee_id="T-01")

    assert result.C_scores == {"G06": 1, "G08": 1, "G10": 1}


def test_pod_d_database_writer_creates_trainee_and_upserts_all_goal_scores(monkeypatch):
    from app.scoring import pod_d

    calls = []

    class Connection:
        def execute(self, statement, params):
            calls.append((str(statement), params))

    class Engine:
        def begin(self):
            from contextlib import contextmanager

            @contextmanager
            def transaction():
                yield Connection()

            return transaction()

        def dispose(self):
            calls.append(("disposed", None))

    monkeypatch.setattr(pod_d, "create_engine", lambda *args, **kwargs: Engine())
    pod_d.save_pod_d_result(RoleplayResult.model_validate(_sample()), "postgresql://unused")

    assert "INSERT INTO trainee_profiles.trainees" in calls[0][0]
    assert calls[0][1] == {"trainee_id": "T-01"}
    assert "ON CONFLICT (trainee_id, section_code, criterion_code)" in calls[1][0]
    assert calls[1][1] == [
        {"trainee_id": "T-01", "criterion_code": "G06", "score": 2},
        {"trainee_id": "T-01", "criterion_code": "G08", "score": 4},
        {"trainee_id": "T-01", "criterion_code": "G10", "score": 1},
    ]
    assert calls[-1] == ("disposed", None)


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


def test_trainee_database_url_is_read_from_its_secret_environment_variable(monkeypatch):
    database_url = "postgresql+psycopg://user:example@localhost:5432/pod_d"
    monkeypatch.setenv("TRAINEE_DB_URL", database_url)

    settings = Settings(_env_file=None)

    assert settings.trainee_db_url is not None
    assert settings.trainee_db_url.get_secret_value() == database_url
    assert database_url not in repr(settings)
