"""Turn validated model output and code signals into a report-ready assessment."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.assessment import (
    Assessment,
    CriterionAssessment,
    ScoringCriterion,
    ScoringOutput,
)
from app.schemas.config import CriterionConfig, ScoringConfig

ADMIN_REVIEW_CONFIDENCE_THRESHOLD = 85.0
ADMIN_REVIEW_MIN_TURNS = 4


class ScoringValidationContext(BaseModel):
    """Validation results keyed by logical exchange number."""

    model_config = ConfigDict(extra="forbid")

    client_exchange_numbers: set[int]
    trainee_exchange_numbers: set[int]
    question_validity: dict[int, bool]
    trainee_signals: dict[int, set[str]]

    @model_validator(mode="after")
    def _valid_exchange_numbers(self) -> "ScoringValidationContext":
        if any(turn < 1 for turn in self.client_exchange_numbers | self.trainee_exchange_numbers):
            raise ValueError("exchange numbers must be positive")
        if not self.trainee_exchange_numbers.issubset(self.client_exchange_numbers):
            raise ValueError("every trainee reply must map to a client question")
        if set(self.question_validity) != self.client_exchange_numbers:
            raise ValueError("question_validity must cover every client exchange")
        if set(self.trainee_signals) != self.trainee_exchange_numbers:
            raise ValueError("trainee_signals must cover every trainee exchange")
        return self


def derive_handled(
    scoring_output: ScoringOutput, config: ScoringConfig
) -> Literal["yes", "partly", "no"]:
    """Whether the client's concern was handled, from the weighted score and the config cutoffs."""
    weights = {criterion.id: criterion.weight for criterion in config.criteria}
    score = sum(item.points * weights[item.id] for item in scoring_output.criteria)
    if score >= config.handled_cutoffs.yes:
        return "yes"
    if score >= config.handled_cutoffs.partly:
        return "partly"
    return "no"


def build_assessment(
    scoring_output: ScoringOutput,
    config: ScoringConfig,
    validation: ScoringValidationContext,
    *,
    handled: Literal["yes", "partly", "no"],
    ended_by_trainee: bool = False,
) -> Assessment:
    """Apply the weighted score, status cutoffs, and proposed confidence formula."""
    configured = {criterion.id: criterion for criterion in config.criteria}
    returned = {criterion.id: criterion for criterion in scoring_output.criteria}
    if configured.keys() != returned.keys():
        missing = sorted(configured.keys() - returned.keys())
        unexpected = sorted(returned.keys() - configured.keys())
        raise ValueError(
            f"scoring criteria do not match rubric (missing={missing}, unexpected={unexpected})"
        )

    results = [
        _criterion_assessment(
            returned[criterion.id],
            criterion,
            config,
            validation,
        )
        for criterion in config.criteria
    ]

    invalid_questions = sum(not valid for valid in validation.question_validity.values())
    confidence = sum(item.weight * item.confidence for item in results)
    confidence -= invalid_questions * config.confidence.invalid_question_penalty
    confidence = min(100.0, max(0.0, confidence))
    if len(validation.trainee_exchange_numbers) < config.confidence.short_session_turns:
        confidence = min(confidence, config.confidence.short_session_cap)

    return Assessment(
        criteria=results,
        handled=handled,
        confidence_score=confidence,
        strengths=scoring_output.strengths,
        gaps=scoring_output.gaps,
        unanswered_objections=scoring_output.unanswered_objections,
        human_review_required=(
            ended_by_trainee
            or confidence <= ADMIN_REVIEW_CONFIDENCE_THRESHOLD
            or len(validation.trainee_exchange_numbers) < ADMIN_REVIEW_MIN_TURNS
        ),
    )


def _criterion_assessment(
    output: ScoringCriterion,
    criterion: CriterionConfig,
    config: ScoringConfig,
    validation: ScoringValidationContext,
) -> CriterionAssessment:
    evidence_turns = [item.turn for item in output.evidence]
    missing_turns = sorted(set(evidence_turns) - validation.trainee_exchange_numbers)
    if missing_turns:
        raise ValueError(
            f"criterion {criterion.id} cites nonexistent trainee exchanges: {missing_turns}"
        )

    if output.points < config.status_cutoffs.partly:
        status = "not_met"
    elif output.points < config.status_cutoffs.met:
        status = "partly"
    else:
        status = "met"

    margin = min(
        abs(output.points - config.status_cutoffs.partly),
        abs(output.points - config.status_cutoffs.met),
    )
    margin_score = min(1.0, margin / config.confidence.status_margin)
    confidence = _criterion_confidence(
        output,
        criterion,
        config,
        validation,
        margin_score,
    )

    return CriterionAssessment(
        id=criterion.id,
        label=criterion.label,
        weight=criterion.weight,
        status=status,
        points=output.points,
        confidence=confidence,
        reason=output.reason,
        evidence=output.evidence,
    )


def _criterion_confidence(
    output: ScoringCriterion,
    criterion: CriterionConfig,
    config: ScoringConfig,
    validation: ScoringValidationContext,
    margin_score: float,
) -> float:
    if output.points > 0 and not output.evidence:
        return 0.0

    question_values = (
        [validation.question_validity[item.turn] for item in output.evidence]
        if output.evidence
        else list(validation.question_validity.values())
    )
    question_score = (
        sum(question_values) / len(question_values) if question_values else 0.0
    )
    weights = config.confidence

    if criterion.signal_keys:
        if output.evidence:
            agreements = []
            for evidence in output.evidence:
                signal_fired = _signal_fired(
                    criterion, validation.trainee_signals[evidence.turn]
                )
                agreements.append(signal_fired == (evidence.polarity == "positive"))
            signal_score = sum(agreements) / len(agreements)
        else:
            signal_score = float(
                not any(
                    _signal_fired(criterion, signals)
                    for signals in validation.trainee_signals.values()
                )
            )
        return 100 * (
            weights.evidence_weight * signal_score
            + weights.question_weight * question_score
            + weights.margin_weight * margin_score
        )

    remaining_weight = weights.question_weight + weights.margin_weight
    if remaining_weight == 0:
        raise ValueError("confidence needs a question or margin weight when signals are absent")
    return 100 * (
        weights.question_weight * question_score + weights.margin_weight * margin_score
    ) / remaining_weight


def _signal_fired(criterion: CriterionConfig, signals: set[str]) -> bool:
    return bool(set(criterion.signal_keys) & signals)
