from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import TurnRole


class Evaluation(BaseModel):
    """The model's judgement of one trainee answer (stored on the trainee `turn` row)."""

    answer_quality: float = Field(ge=0, le=1)
    # Which items of the scenario's `good_answer_contains` this answer met (the item text).
    checklist_met: list[str] = Field(default_factory=list)
    evasive: bool = False
    composure: float = Field(default=1.0, ge=0, le=1)
    quote: str  # short exact quote from the trainee's answer backing this judgement
    proposed_level: int = Field(ge=1, le=4)  # the model's suggestion; the code guard decides


class TurnOutput(BaseModel):
    """What the per-turn LLM call must return (one call: evaluation + reply)."""

    evaluation: Evaluation
    reply: str
    refs: list[UUID] = Field(default_factory=list)  # proposal segment ids the reply relied on


class Turn(BaseModel):
    """One stored chat message (a `turn` row). Append-only.

    `idx` starts at 0. The program's result format numbers messages from 1, so
    result turn number = idx + 1, and the persona is called "client" there.
    """

    id: UUID
    session_id: UUID
    idx: int
    role: TurnRole
    content: str
    escalation_level: int | None = Field(default=None, ge=1, le=4)  # persona rows only
    refs: list[UUID] = Field(default_factory=list)  # persona rows only
    evaluation: Evaluation | None = None  # trainee rows only
    created_at: datetime
