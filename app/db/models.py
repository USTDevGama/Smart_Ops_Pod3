"""The 5 tables. Only Dev D writes migrations for changes here.

Scoring, review, reports, users, the AI-call log and the audit log are not built yet; their
tables were dropped in migration 0002 and come back when those features are built.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonType, created_at_col, enum_col, uuid_pk
from app.schemas.enums import (
    ConfigKind,
    ConfigStatus,
    EndReason,
    FileType,
    ProposalStatus,
    SegmentKind,
    SessionStatus,
    TurnRole,
)


class ConfigVersion(Base):
    """Every saved persona and scenario. Published rows never change."""

    __tablename__ = "config_version"
    __table_args__ = (UniqueConstraint("kind", "key", "version_no"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[ConfigKind] = mapped_column(enum_col(ConfigKind, "config_kind"))
    key: Mapped[str] = mapped_column(String(100))
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[ConfigStatus] = mapped_column(enum_col(ConfigStatus, "config_status"))
    config: Mapped[dict] = mapped_column(JsonType)
    created_at: Mapped[datetime] = created_at_col()


class Proposal(Base):
    """An uploaded file and what we learned from it."""

    __tablename__ = "proposal"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_ref: Mapped[str] = mapped_column(String(64), index=True)  # login user (X-Dev-User)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[FileType] = mapped_column(enum_col(FileType, "file_type"))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    blob_uri: Mapped[str] = mapped_column(String(500))
    status: Mapped[ProposalStatus] = mapped_column(enum_col(ProposalStatus, "proposal_status"))
    brief: Mapped[dict | None] = mapped_column(JsonType)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()  # also drives the 30-day purge


class ProposalSegment(Base):
    """The proposal split into citable chunks."""

    __tablename__ = "proposal_segment"
    __table_args__ = (UniqueConstraint("proposal_id", "seq"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("proposal.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)  # 1 for plain text files
    kind: Mapped[SegmentKind] = mapped_column(enum_col(SegmentKind, "segment_kind"))
    text: Mapped[str] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)


class RoleplaySession(Base):
    """One roleplay run. Pins the exact persona and scenario versions it used."""

    __tablename__ = "session"

    id: Mapped[uuid.UUID] = uuid_pk()
    trainee_ref: Mapped[str] = mapped_column(String(64), index=True)  # login user (X-Dev-User)
    # Optional: a session can run on the scenario alone. No cascade: the purge job must not
    # delete a proposal still used by a live session.
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proposal.id"))
    persona_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("config_version.id"))
    scenario_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("config_version.id"))
    status: Mapped[SessionStatus] = mapped_column(enum_col(SessionStatus, "session_status"))
    end_reason: Mapped[EndReason | None] = mapped_column(enum_col(EndReason, "end_reason"))
    started_at: Mapped[datetime] = created_at_col()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # drives the purge


class Turn(Base):
    """The chat, one row per message. Never edited: the source of truth and the citation target."""

    __tablename__ = "turn"
    __table_args__ = (
        UniqueConstraint("session_id", "idx"),
        UniqueConstraint("session_id", "idempotency_key"),
        CheckConstraint(
            "escalation_level IS NULL OR (escalation_level BETWEEN 1 AND 4)",
            name="ck_turn_escalation_level",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("session.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer)
    role: Mapped[TurnRole] = mapped_column(enum_col(TurnRole, "turn_role"))
    content: Mapped[str] = mapped_column(Text)
    escalation_level: Mapped[int | None] = mapped_column(Integer)  # persona rows only
    refs: Mapped[list | None] = mapped_column(JsonType)  # persona rows: proposal_segment ids
    evaluation: Mapped[dict | None] = mapped_column(JsonType)  # trainee rows only
    idempotency_key: Mapped[str | None] = mapped_column(String(100))  # trainee rows only
    created_at: Mapped[datetime] = created_at_col()
