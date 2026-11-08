"""Raw scoring-model output and code-validated assessment shapes."""

from typing import Literal

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

    rubric_version: str = Field(min_length=1)
    criteria: list[CriterionAssessment] = Field(min_length=1)
    handled: Literal["yes", "partly", "no"]
    confidence_score: float = Field(ge=0, le=100)
    strengths: list[ScoringNote] = Field(default_factory=list)
    gaps: list[ScoringNote] = Field(default_factory=list)
    unanswered_objections: list[str] = Field(default_factory=list)
    human_review_required: bool = True

    @model_validator(mode="after")
    def _consistent_rubric(self) -> "Assessment":
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


# --- The program's result format ("roleplay-result"), what leaves the pod --------------------


class ResultTurn(BaseModel):
    turn: int = Field(ge=1)  # 1-based position of a message; client and trainee count separately
    role: Literal["client", "trainee"]
    text: str


class ResultBody(BaseModel):
    pushback_peak_step: int = Field(ge=1, le=4)
    handled: Literal["yes", "partly", "no"]
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str]
    evidence_turns: list[int]


class RoleplayResult(BaseModel):
    """Outgoing Pod D contract, distinct from the internal criterion-scoring output."""

    contract: Literal["roleplay-result"] = "roleplay-result"
    session_id: str
    scenario_id: str
    persona_version: str
    turns: list[ResultTurn] = Field(min_length=1)
    result: ResultBody
    human_review_required: bool = True

    @model_validator(mode="after")
    def _evidence_points_at_real_turns(self) -> "RoleplayResult":
        existing = {turn.turn for turn in self.turns}
        missing = [number for number in self.result.evidence_turns if number not in existing]
        if missing:
            raise ValueError(f"evidence_turns refer to turns that do not exist: {missing}")
        return self
