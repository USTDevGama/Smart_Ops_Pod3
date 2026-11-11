import pytest
from pydantic import ValidationError

from app.schemas import ScoringConfig, ScoringOutput
from app.scoring import ScoringValidationContext, build_assessment
from app.scoring.processor import derive_handled
from tests.conftest import load_sample


def _inputs():
    output = ScoringOutput.model_validate(load_sample("results/llm_output.json"))
    config = ScoringConfig.model_validate(load_sample("scoring/default.json"))
    validation = ScoringValidationContext(
        client_exchange_numbers={1, 2, 3, 4},
        trainee_exchange_numbers={1, 2, 3, 4},
        question_validity={1: True, 2: True, 3: True, 4: True},
        trainee_signals={
            1: set(),
            2: set(),
            3: {"has_specifics", "kept_composure", "grounded"},
            4: {"has_specifics", "has_commitment"},
        },
    )
    return output, config, validation


def test_clean_sample_scores_and_confidence_match_the_formula_example():
    output, config, validation = _inputs()

    assessment = build_assessment(output, config, validation, handled="partly")

    # 100 * (0.5*0.25 + 0.7*0.30 + 0.4*0.25 + 0.2*0.20)
    assert assessment.overall_score == pytest.approx(47.5)
    assert [item.confidence for item in assessment.criteria] == pytest.approx(
        [100, 60, 100, 100]  # C2 sits exactly on the "met" cutoff, so its margin term is 0
    )
    assert assessment.confidence_score == pytest.approx(88)
    assert assessment.human_review_required is False
    assert [item.status for item in assessment.criteria] == [
        "partly",
        "met",
        "partly",
        "not_met",
    ]


def test_invalid_client_question_reduces_confidence_not_score():
    output, config, validation = _inputs()
    validation.question_validity[3] = False

    assessment = build_assessment(output, config, validation, handled="partly")

    assert assessment.overall_score == pytest.approx(47.5)
    assert assessment.criteria[1].confidence == pytest.approx(50)
    assert assessment.criteria[2].confidence == pytest.approx(80)
    assert assessment.confidence_score == pytest.approx(75)  # 80 base minus the 5-point penalty


def test_bad_signal_agreement_only_reduces_its_criterion_confidence():
    output, config, validation = _inputs()
    data = output.model_dump(mode="python")
    data["criteria"][2]["evidence"] = [{"turn": 2, "polarity": "positive"}]
    output = ScoringOutput.model_validate(data)

    assessment = build_assessment(output, config, validation, handled="partly")

    assert assessment.overall_score == pytest.approx(47.5)
    assert assessment.criteria[2].confidence == pytest.approx(60)
    assert assessment.confidence_score == pytest.approx(78)


def test_invalid_evidence_turn_is_rejected_before_report_generation():
    output, config, validation = _inputs()
    data = output.model_dump(mode="python")
    data["criteria"][0]["evidence"] = [{"turn": 99, "polarity": "positive"}]
    output = ScoringOutput.model_validate(data)

    with pytest.raises(ValueError, match="nonexistent trainee exchanges"):
        build_assessment(output, config, validation, handled="partly")


def test_short_session_confidence_is_capped():
    output, config, _ = _inputs()
    data = output.model_dump(mode="python")
    for criterion in data["criteria"]:
        criterion["evidence"] = [{"turn": 1, "polarity": "positive"}]
    output = ScoringOutput.model_validate(data)
    validation = ScoringValidationContext(
        client_exchange_numbers={1, 2, 3},
        trainee_exchange_numbers={1, 2},
        question_validity={1: True, 2: True, 3: True},
        trainee_signals={
            1: {"has_specifics", "kept_composure", "grounded", "has_commitment"},
            2: set(),
        },
    )

    assessment = build_assessment(output, config, validation, handled="partly")

    assert assessment.confidence_score == pytest.approx(60)


@pytest.mark.parametrize(
    ("points", "turns", "ended_by_trainee", "expected_review"),
    [
        (0.9, 4, False, False),
        (0.3775, 4, False, True),
        (0.9, 3, False, True),
        (0.9, 4, True, True),
    ],
)
def test_admin_review_threshold_and_minimum_turns(
    points, turns, ended_by_trainee, expected_review
):
    output, config, _ = _inputs()
    config = config.model_copy(
        update={
            "criteria": [
                criterion.model_copy(update={"signal_keys": []})
                for criterion in config.criteria
            ]
        }
    )
    output_data = output.model_dump(mode="python")
    for criterion in output_data["criteria"]:
        criterion["points"] = points
        criterion["evidence"] = [{"turn": 1, "polarity": "positive"}]
    output = ScoringOutput.model_validate(output_data)
    exchanges = set(range(1, turns + 1))
    validation = ScoringValidationContext(
        client_exchange_numbers=exchanges,
        trainee_exchange_numbers=exchanges,
        question_validity={turn: True for turn in exchanges},
        trainee_signals={turn: set() for turn in exchanges},
    )

    assessment = build_assessment(
        output,
        config,
        validation,
        handled="partly",
        ended_by_trainee=ended_by_trainee,
    )

    assert assessment.confidence_score == pytest.approx(
        85 if points == 0.3775 else 100
    )
    assert assessment.human_review_required is expected_review


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ([1, 1, 1, 1], "yes"),
        ([0.7, 0.7, 0.7, 0.7], "yes"),  # on the cutoff counts as reached
        ([0.5, 0.5, 0.5, 0.5], "partly"),
        ([0.4, 0.4, 0.4, 0.4], "partly"),
        ([0.2, 0.2, 0.2, 0.2], "no"),
    ],
)
def test_handled_follows_the_weighted_score(points, expected):
    output, config, _ = _inputs()
    data = output.model_dump(mode="python")
    for criterion, value in zip(data["criteria"], points, strict=True):
        criterion["points"] = value
    output = ScoringOutput.model_validate(data)

    assert derive_handled(output, config) == expected


def test_context_requires_signal_turns_to_map_to_client_questions():
    with pytest.raises(ValidationError, match="map to a client question"):
        ScoringValidationContext(
            client_exchange_numbers={1},
            trainee_exchange_numbers={2},
            question_validity={1: True},
            trainee_signals={2: set()},
        )
