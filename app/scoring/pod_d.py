"""Deterministic mapping from Pod C criterion points to the Pod D goal-score contract."""

from app.schemas.assessment import Assessment, PodDGoalId, RoleplayResult

_GOAL_CRITERIA: dict[PodDGoalId, tuple[str, ...]] = {
    "G06": ("C1", "C3"),
    "G08": ("C2",),
    "G10": ("C4",),
}


def build_pod_d_result(assessment: Assessment, trainee_id: str) -> RoleplayResult:
    """Map normalized criterion points to 0-5 goal scores using criterion weights."""
    criteria = {criterion.id: criterion for criterion in assessment.criteria}
    required = {criterion_id for ids in _GOAL_CRITERIA.values() for criterion_id in ids}
    missing = sorted(required - criteria.keys())
    if missing:
        raise ValueError(f"assessment is missing Pod D criteria: {', '.join(missing)}")

    scores: dict[PodDGoalId, float] = {}
    for goal_id, criterion_ids in _GOAL_CRITERIA.items():
        goal_criteria = [criteria[criterion_id] for criterion_id in criterion_ids]
        total_weight = sum(criterion.weight for criterion in goal_criteria)
        if total_weight <= 0:
            raise ValueError(f"criteria mapped to {goal_id} have zero combined weight")
        weighted_points = sum(
            criterion.points * criterion.weight for criterion in goal_criteria
        )
        scores[goal_id] = 5 * weighted_points / total_weight

    return RoleplayResult(trainee_id=trainee_id, C_scores=scores)
