from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import FileType, ProposalStatus, SegmentKind


class Segment(BaseModel):
    """One citable chunk of the proposal (a `proposal_segment` row)."""

    id: UUID
    proposal_id: UUID
    seq: int
    page: int
    kind: SegmentKind
    text: str


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


class ProposalOut(BaseModel):
    """What the API returns for an uploaded proposal. No file contents, no storage path."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    file_type: FileType
    status: ProposalStatus
    error: str | None = None
    brief: Brief | None = None
    created_at: datetime
