from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import SegmentKind


class Segment(BaseModel):
    """One citable chunk of the proposal (a `proposal_segment` row)."""

    id: UUID
    proposal_id: UUID
    seq: int
    page: int
    kind: SegmentKind
    text: str
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)


class BriefItem(BaseModel):
    """One thing the ingest LLM call found in the proposal.

    `segment_ids` are the chunks it came from. They are required so the persona can only
    challenge something the proposal really says (code checks the ids exist).
    """

    kind: Literal["claim", "assumption", "risk", "weak_point", "inconsistency"]
    text: str
    segment_ids: list[UUID] = Field(min_length=1)


class Brief(BaseModel):
    """Structured summary of a proposal, stored on `proposal.brief`."""

    summary: str
    items: list[BriefItem]
