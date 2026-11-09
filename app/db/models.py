"""The 5 tables. Only Dev D writes migrations for changes here.

Scoring, review, reports, users, the AI-call log and the audit log are not stored in dedicated
tables. Scoring and reports use the session, pinned configuration, and turns as inputs. Review
history or score snapshots would need a separate storage decision and migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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
    IngestStatus,
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


class Profile(Base):
    """A trainee's uploaded resume. Whatever the pipeline extracts is kept as JSON."""

    __tablename__ = "profile"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_ref: Mapped[str] = mapped_column(String(64), index=True)  # login user (X-Dev-User)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[FileType] = mapped_column(enum_col(FileType, "file_type"))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    blob_uri: Mapped[str] = mapped_column(String(500))
    status: Mapped[IngestStatus] = mapped_column(enum_col(IngestStatus, "ingest_status"))
    content: Mapped[dict | None] = mapped_column(JsonType)  # what the pipeline extracted
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()  # also drives the 30-day purge


class DemandDocument(Base):
    """The project demand document, uploaded by an admin (master data from the Gama team).

    It is short, so everything the pipeline extracts goes to the agent as it is; no chunking.
    """

    __tablename__ = "demand_document"

    id: Mapped[uuid.UUID] = uuid_pk()
    uploaded_by: Mapped[str] = mapped_column(String(64))  # the admin (X-Dev-User)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[FileType] = mapped_column(enum_col(FileType, "file_type"))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    blob_uri: Mapped[str] = mapped_column(String(500))
    status: Mapped[IngestStatus] = mapped_column(enum_col(IngestStatus, "ingest_status"))
    content: Mapped[dict | None] = mapped_column(JsonType)  # what the pipeline extracted
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class RoleplaySession(Base):
    """One roleplay run. Pins the persona, profile, and demand document it used."""

    __tablename__ = "session"

    id: Mapped[uuid.UUID] = uuid_pk()
    trainee_ref: Mapped[str] = mapped_column(String(64), index=True)  # login user (X-Dev-User)
    # The trainee's profile. The API requires it for new sessions; old rows may be empty. No
    # cascade: the purge job must not delete a profile still used by a live session.
    profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profile.id"))
    persona_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("config_version.id"))
    # The demand document in force when the chat started. No cascade, like the profile.
    demand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("demand_document.id"))
    # No longer set: the agent picks scenarios itself. Kept so old sessions still load.
    scenario_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("config_version.id"))
    status: Mapped[SessionStatus] = mapped_column(enum_col(SessionStatus, "session_status"))
    end_reason: Mapped[EndReason | None] = mapped_column(enum_col(EndReason, "end_reason"))
    started_at: Mapped[datetime] = created_at_col()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # drives the purge


class Turn(Base):
    """The chat, one row per message. Never edited: the source of truth."""

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
    evaluation: Mapped[dict | None] = mapped_column(JsonType)  # trainee rows only
    idempotency_key: Mapped[str | None] = mapped_column(String(100))  # trainee rows only
    created_at: Mapped[datetime] = created_at_col()
