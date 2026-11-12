"""Deterministic mapping from Pod C criterion points to the Pod D goal-score contract."""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import create_engine, text

from app.schemas.assessment import Assessment, PodDGoalId, RoleplayResult

_GOAL_CRITERIA: dict[PodDGoalId, tuple[str, ...]] = {
    "G06": ("C1", "C3"),
    "G08": ("C2",),
    "G10": ("C4",),
}

_INSERT_TRAINEE = text(
    """
    INSERT INTO trainee_profiles.trainees (trainee_id)
    VALUES (:trainee_id)
    ON CONFLICT (trainee_id) DO NOTHING
    """
)

_UPSERT_SCORE = text(
    """
    INSERT INTO trainee_profiles.trainee_scores
        (trainee_id, section_code, criterion_code, score)
    VALUES
        (:trainee_id, 'C', :criterion_code, :score)
    ON CONFLICT (trainee_id, section_code, criterion_code)
    DO UPDATE SET score = EXCLUDED.score
    """
)


def build_pod_d_result(assessment: Assessment, trainee_id: str) -> RoleplayResult:
    """Map normalized points to the database's integer 1-5 scale, rounding halves up."""
    criteria = {criterion.id: criterion for criterion in assessment.criteria}
    required = {criterion_id for ids in _GOAL_CRITERIA.values() for criterion_id in ids}
    missing = sorted(required - criteria.keys())
    if missing:
        raise ValueError(f"assessment is missing Pod D criteria: {', '.join(missing)}")

    scores: dict[PodDGoalId, int] = {}
    for goal_id, criterion_ids in _GOAL_CRITERIA.items():
        goal_criteria = [criteria[criterion_id] for criterion_id in criterion_ids]
        decimal_weights = [Decimal(str(criterion.weight)) for criterion in goal_criteria]
        decimal_total_weight = sum(decimal_weights)
        if decimal_total_weight <= 0:
            raise ValueError(f"criteria mapped to {goal_id} have zero combined weight")
        weighted_points = sum(
            Decimal(str(criterion.points)) * weight
            for criterion, weight in zip(goal_criteria, decimal_weights, strict=True)
        )
        scaled = Decimal(5) * weighted_points / decimal_total_weight
        rounded = int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        scores[goal_id] = min(5, max(1, rounded))

    return RoleplayResult(trainee_id=trainee_id, C_scores=scores)


def save_pod_d_result(result: RoleplayResult, database_url: str) -> None:
    """Create the trainee row if needed, then upsert its three section-C goal scores."""
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(_INSERT_TRAINEE, {"trainee_id": result.trainee_id})
            connection.execute(
                _UPSERT_SCORE,
                [
                    {
                        "trainee_id": result.trainee_id,
                        "criterion_code": goal_id,
                        "score": score,
                    }
                    for goal_id, score in result.C_scores.items()
                ],
            )
    finally:
        engine.dispose()
