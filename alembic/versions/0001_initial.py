"""initial schema: the 5 tables

config_version, profile, profile_segment, session, turn. There is no user table: the login
user is stored as plain text (`owner_ref`, `trainee_ref`). Scoring, review, reports and the logs
get their own migration when those features are built.

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def _pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _created(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "config_version",
        _pk(),
        sa.Column("kind", _enum("config_kind", "persona", "scenario", "demand"), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column(
            "status", _enum("config_status", "draft", "published", "retired"), nullable=False
        ),
        sa.Column("config", JSON_T, nullable=False),
        _created(),
        sa.UniqueConstraint("kind", "key", "version_no"),
    )

    op.create_table(
        "profile",
        _pk(),
        sa.Column("owner_ref", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", _enum("file_type", "pdf", "docx", "txt"), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("blob_uri", sa.String(500), nullable=False),
        sa.Column(
            "status",
            _enum("profile_status", "queued", "extracting", "ready", "failed"),
            nullable=False,
        ),
        sa.Column("brief", JSON_T),
        sa.Column("error", sa.Text()),
        _created(),
    )
    op.create_index("ix_profile_owner_ref", "profile", ["owner_ref"])
    op.create_index("ix_profile_sha256", "profile", ["sha256"])

    op.create_table(
        "profile_segment",
        _pk(),
        sa.Column(
            "profile_id",
            sa.Uuid(),
            sa.ForeignKey("profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("kind", _enum("segment_kind", "text", "ocr"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("ocr_confidence", sa.Float()),
        sa.UniqueConstraint("profile_id", "seq"),
    )

    op.create_table(
        "session",
        _pk(),
        sa.Column("trainee_ref", sa.String(64), nullable=False),
        sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("profile.id")),
        sa.Column(
            "persona_version_id", sa.Uuid(), sa.ForeignKey("config_version.id"), nullable=False
        ),
        sa.Column("demand_version_id", sa.Uuid(), sa.ForeignKey("config_version.id")),
        sa.Column("scenario_version_id", sa.Uuid(), sa.ForeignKey("config_version.id")),
        sa.Column("status", _enum("session_status", "active", "ended"), nullable=False),
        sa.Column(
            "end_reason",
            _enum(
                "end_reason",
                "trainee_ended",
                "turn_cap",
                "concerns_resolved",
                "time_limit",
                "admin_ended",
            ),
        ),
        _created("started_at"),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_session_trainee_ref", "session", ["trainee_ref"])

    op.create_table(
        "turn",
        _pk(),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("role", _enum("turn_role", "persona", "trainee"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("escalation_level", sa.Integer()),
        sa.Column("refs", JSON_T),
        sa.Column("evaluation", JSON_T),
        sa.Column("idempotency_key", sa.String(100)),
        _created(),
        sa.UniqueConstraint("session_id", "idx"),
        sa.UniqueConstraint("session_id", "idempotency_key"),
        sa.CheckConstraint(
            "escalation_level IS NULL OR (escalation_level BETWEEN 1 AND 4)",
            name="ck_turn_escalation_level",
        ),
    )


def downgrade() -> None:
    for table in ("turn", "session", "profile_segment", "profile", "config_version"):
        op.drop_table(table)
