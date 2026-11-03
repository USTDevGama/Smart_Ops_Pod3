from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import AssessmentStatus, Confidence, Polarity


class Finding(BaseModel):
    """One cited quote. `turn_id` + `quote` are checked by code (BR-12)."""

    turn_id: UUID
    quote: str
    polarity: Polarity


class LLMDimensionScore(BaseModel):
    key: str
    score: float = Field(ge=0, le=100)
    rationale: str
    findings: list[Finding] = Field(default_factory=list)


class ScoringOutput(BaseModel):
    """What the scoring LLM call must return."""

    dimensions: list[LLMDimensionScore]


class DimensionResult(BaseModel):
    """One dimension after the code checks and the blend."""

    key: str
    weight: float
    code_score: float | None = None
    llm_score: float | None = None
    score: float | None = None  # blended; None if the dimension lost all its evidence
    rationale: str = ""
    evidence: list[Finding] = Field(default_factory=list)  # only findings that passed the check


class Assessment(BaseModel):
    """The suggested score for a session (an `assessment` row). Our richer, internal view."""

    id: UUID
    session_id: UUID
    run_no: int
    status: AssessmentStatus
    composite: float | None = None
    band: str | None = None
    confidence: Confidence | None = None
    dimensions: list[DimensionResult] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)  # e.g. unresolved_at_limit, ended_early
    created_at: datetime


# --- The program's result format ("roleplay-result"), what leaves the pod --------------------
# Shape taken from the seed pack's contract. Two points are ASSUMPTIONS to confirm with the TPM:
# the allowed values of `handled` (the seed only shows "partly"), and the 1-4 step range.


class ResultTurn(BaseModel):
    turn: int = Field(ge=1)  # 1-based position of the message; client and trainee both count
    role: Literal["client", "trainee"]
    text: str


class ResultBody(BaseModel):
    pushback_peak_step: int = Field(ge=1, le=4)  # toughest escalation step the client reached
    handled: Literal["yes", "partly", "no"]  # ASSUMPTION: confirm the allowed values
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str]
    evidence_turns: list[int]  # turn numbers that back the strengths and gaps


class RoleplayResult(BaseModel):
    contract: Literal["roleplay-result"] = "roleplay-result"
    session_id: str
    scenario_id: str
    persona_version: str
    turns: list[ResultTurn] = Field(min_length=1)
    result: ResultBody
    human_review_required: bool = True

    @model_validator(mode="after")
    def _evidence_points_at_real_turns(self) -> "RoleplayResult":
        existing = {t.turn for t in self.turns}
        missing = [n for n in self.result.evidence_turns if n not in existing]
        if missing:
            raise ValueError(f"evidence_turns refer to turns that do not exist: {missing}")
        return self
