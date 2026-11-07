import pytest
from pydantic import ValidationError

from app.schemas import ScoringConfig, ScoringOutput
from app.scoring import ScoringValidationContext, build_assessment
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
            3: {"has_date", "has_cost"},
            4: {"has_ownership", "has_commitment"},
        },
    )
    return output, config, validation


def test_clean_sample_scores_and_confidence_match_the_formula_example():
    output, config, validation = _inputs()

    assessment = build_assessment(output, config, validation, handled="partly")

    assert assessment.overall_score == pytest.approx(45.0)
    assert [item.confidence for item in assessment.criteria] == pytest.approx(
        [100, 75, 100, 100]
    )
    assert assessment.confidence_score == pytest.approx(93.75)
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

    assert assessment.overall_score == pytest.approx(45.0)
    assert assessment.criteria[1].confidence == pytest.approx(57.5)
    assert assessment.criteria[2].confidence == pytest.approx(65)
    assert assessment.confidence_score == pytest.approx(70.625)


def test_bad_signal_agreement_only_reduces_its_criterion_confidence():
    output, config, validation = _inputs()
    data = output.model_dump(mode="python")
    data["criteria"][2]["evidence"] = [{"turn": 2, "polarity": "positive"}]
    output = ScoringOutput.model_validate(data)

    assessment = build_assessment(output, config, validation, handled="partly")

    assert assessment.overall_score == pytest.approx(45.0)
    assert assessment.criteria[2].confidence == pytest.approx(60)
    assert assessment.confidence_score == pytest.approx(83.75)


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
            1: {"has_ownership", "has_date", "has_cost", "has_commitment"},
            2: set(),
        },
    )

    assessment = build_assessment(output, config, validation, handled="partly")

    assert assessment.confidence_score == pytest.approx(60)


def test_context_requires_signal_turns_to_map_to_client_questions():
    with pytest.raises(ValidationError, match="map to a client question"):
        ScoringValidationContext(
            client_exchange_numbers={1},
            trainee_exchange_numbers={2},
            question_validity={1: True},
            trainee_signals={2: set()},
        )
