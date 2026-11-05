from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import SegmentKind


class Segment(BaseModel):
    """One citable chunk of the profile (a `profile_segment` row)."""

    id: UUID
    profile_id: UUID
    seq: int
    page: int
    kind: SegmentKind
    text: str
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)


class BriefItem(BaseModel):
    """One thing the ingest LLM call found in the profile.

    `segment_ids` are the chunks it came from. They are required so the persona can only
    challenge something the profile really says (code checks the ids exist).
    """

    kind: Literal["claim", "assumption", "risk", "weak_point", "inconsistency"]
    text: str
    segment_ids: list[UUID] = Field(min_length=1)


class Brief(BaseModel):
    """Structured summary of a profile, stored on `profile.brief`."""

    summary: str
    items: list[BriefItem]
