"""The 12 tables (plan section 7). Only Dev D writes migrations for changes here."""

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
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonType, created_at_col, enum_col, uuid_pk
from app.schemas.enums import (
    AssessmentStatus,
    Confidence,
    ConfigKind,
    ConfigStatus,
    EndReason,
    FileType,
    Polarity,
    ProposalStatus,
    ReportFormat,
    ReviewDecision,
    SegmentKind,
    SessionStatus,
    TurnRole,
)


class AppUser(Base):
    """People known to the app. No passwords and no names are stored."""

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    idp_sub: Mapped[str] = mapped_column(String(255), unique=True)  # user id in the login system
    trainee_ref: Mapped[str | None] = mapped_column(String(64), unique=True)  # sent to other pods
    cohort_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = created_at_col()


class ConfigVersion(Base):
    """Every saved persona, scenario and scoring profile. Published rows never change."""

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
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[FileType] = mapped_column(enum_col(FileType, "file_type"))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    blob_uri: Mapped[str] = mapped_column(String(500))
    status: Mapped[ProposalStatus] = mapped_column(enum_col(ProposalStatus, "proposal_status"))
    brief: Mapped[dict | None] = mapped_column(JsonType)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()  # also drives the 30-day purge


class ProposalSegment(Base):
    """The proposal's text as markdown: one row per proposal for now."""

    __tablename__ = "proposal_segment"
    __table_args__ = (UniqueConstraint("proposal_id", "seq"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("proposal.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)  # always 1 for now
    kind: Mapped[SegmentKind] = mapped_column(enum_col(SegmentKind, "segment_kind"))
    text: Mapped[str] = mapped_column(Text)


class RoleplaySession(Base):
    """One roleplay run. Pins the exact persona, scenario and scoring versions it used."""

    __tablename__ = "session"

    id: Mapped[uuid.UUID] = uuid_pk()
    trainee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    # Optional: a session can run on the scenario alone. No cascade: the purge job must not
    # delete a proposal still used by a live session.
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proposal.id"))
    persona_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("config_version.id"))
    scenario_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("config_version.id"))
    scoring_profile_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("config_version.id"))
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


class Assessment(Base):
    """The suggested score for a session. A re-score adds a new run_no."""

    __tablename__ = "assessment"
    __table_args__ = (UniqueConstraint("session_id", "run_no"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("session.id", ondelete="CASCADE"))
    run_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[AssessmentStatus] = mapped_column(
        enum_col(AssessmentStatus, "assessment_status")
    )
    composite: Mapped[float | None] = mapped_column(Float)
    band: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[Confidence | None] = mapped_column(enum_col(Confidence, "confidence"))
    dimensions: Mapped[list | None] = mapped_column(JsonType)
    details: Mapped[dict | None] = mapped_column(JsonType)  # flags + numbers behind confidence
    created_at: Mapped[datetime] = created_at_col()


class AssessmentEvidence(Base):
    """One cited quote. The turn_id link is what keeps a finding grounded (BR-12)."""

    __tablename__ = "assessment_evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.id", ondelete="CASCADE")
    )
    dimension: Mapped[str] = mapped_column(String(50))
    turn_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("turn.id", ondelete="CASCADE"))
    quote: Mapped[str] = mapped_column(Text)
    polarity: Mapped[Polarity] = mapped_column(enum_col(Polarity, "polarity"))


class Review(Base):
    """The admin's decision on an assessment."""

    __tablename__ = "review"

    id: Mapped[uuid.UUID] = uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.id", ondelete="CASCADE")
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    decision: Mapped[ReviewDecision] = mapped_column(enum_col(ReviewDecision, "review_decision"))
    final_score: Mapped[float] = mapped_column(Float)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class Report(Base):
    """A generated PDF/HTML file (the file itself lives in blob storage)."""

    __tablename__ = "report"

    id: Mapped[uuid.UUID] = uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.id", ondelete="CASCADE")
    )
    format: Mapped[ReportFormat] = mapped_column(enum_col(ReportFormat, "report_format"))
    blob_uri: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at_col()


class LlmCallLog(Base):
    """Every model call: cost control and the per-session call cap. No prompt bodies."""

    __tablename__ = "llm_call_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # session or proposal id
    purpose: Mapped[str] = mapped_column(String(50))  # brief / opening / turn / score
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = created_at_col()


class AuditLog(Base):
    """Who did what (BR-13): config changes, reviews, report downloads, purges."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detail: Mapped[dict | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = created_at_col()
