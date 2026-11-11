"""Raw scoring-model output and code-validated assessment shapes."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoringEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn: int = Field(ge=1)
    polarity: Literal["positive", "negative"]


class ScoringCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    points: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    evidence: list[ScoringEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_evidence_turns(self) -> "ScoringCriterion":
        turns = [item.turn for item in self.evidence]
        if len(turns) != len(set(turns)):
            raise ValueError("evidence turns must be unique within a criterion")
        return self


class ScoringNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    evidence_turns: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_turns(self) -> "ScoringNote":
        if any(turn < 1 for turn in self.evidence_turns):
            raise ValueError("evidence_turns must be positive exchange numbers")
        if len(self.evidence_turns) != len(set(self.evidence_turns)):
            raise ValueError("evidence_turns must be unique")
        return self


class ScoringOutput(BaseModel):
    """Final criterion-level output supplied by the conversation-agent component."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[ScoringCriterion] = Field(min_length=1)
    strengths: list[ScoringNote] = Field(default_factory=list)
    gaps: list[ScoringNote] = Field(default_factory=list)
    unanswered_objections: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_criteria(self) -> "ScoringOutput":
        keys = [criterion.id for criterion in self.criteria]
        if len(keys) != len(set(keys)):
            raise ValueError("criterion ids must be unique")
        return self


class CriterionAssessment(BaseModel):
    """One criterion after weights, status, evidence, and confidence are validated."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    weight: float = Field(ge=0, le=1)
    status: Literal["not_met", "partly", "met"]
    points: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1)
    evidence: list[ScoringEvidence] = Field(default_factory=list)


class Assessment(BaseModel):
    """Validated, report-ready score; it is derived from a session, not a DB row."""

    criteria: list[CriterionAssessment] = Field(min_length=1)
    handled: Literal["yes", "partly", "no"]
    confidence_score: float = Field(ge=0, le=100)
    strengths: list[ScoringNote] = Field(default_factory=list)
    gaps: list[ScoringNote] = Field(default_factory=list)
    unanswered_objections: list[str] = Field(default_factory=list)
    human_review_required: bool = True

    @model_validator(mode="after")
    def _consistent_criteria(self) -> "Assessment":
        keys = [criterion.id for criterion in self.criteria]
        if len(keys) != len(set(keys)):
            raise ValueError("criterion ids must be unique")

        total_weight = sum(criterion.weight for criterion in self.criteria)
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(f"criterion weights must sum to 1 (got {total_weight})")
        return self

    @property
    def overall_score(self) -> float:
        return 100 * sum(item.points * item.weight for item in self.criteria)


# --- The Pod D result contract ---------------------------------------------------------------


PodDGoalId = Literal["G06", "G08", "G10"]
PodDGoalScore = Annotated[float, Field(ge=0, le=5)]


class RoleplayResult(BaseModel):
    """Only the authenticated trainee id and deterministic Pod D goal scores leave the pod."""

    model_config = ConfigDict(extra="forbid")

    trainee_id: str = Field(min_length=1)
    C_scores: dict[PodDGoalId, PodDGoalScore] = Field(min_length=3, max_length=3)
