"""initial schema: the 12 tables

Revision ID: 0001
Revises:
Create Date: 2026-11-03
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
        "app_user",
        _pk(),
        sa.Column("idp_sub", sa.String(255), nullable=False, unique=True),
        sa.Column("trainee_ref", sa.String(64), unique=True),
        sa.Column("cohort_id", sa.String(64)),
        _created(),
    )
    op.create_index("ix_app_user_cohort_id", "app_user", ["cohort_id"])

    op.create_table(
        "config_version",
        _pk(),
        sa.Column(
            "kind", _enum("config_kind", "persona", "scenario", "scoring_profile"), nullable=False
        ),
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
        "proposal",
        _pk(),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", _enum("file_type", "pdf", "docx", "txt"), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("blob_uri", sa.String(500), nullable=False),
        sa.Column(
            "status",
            _enum("proposal_status", "queued", "extracting", "ready", "failed"),
            nullable=False,
        ),
        sa.Column("brief", JSON_T),
        sa.Column("error", sa.Text()),
        _created(),
    )
    op.create_index("ix_proposal_sha256", "proposal", ["sha256"])

    op.create_table(
        "proposal_segment",
        _pk(),
        sa.Column(
            "proposal_id",
            sa.Uuid(),
            sa.ForeignKey("proposal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("kind", _enum("segment_kind", "text", "ocr"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("ocr_confidence", sa.Float()),
        sa.UniqueConstraint("proposal_id", "seq"),
    )

    op.create_table(
        "session",
        _pk(),
        sa.Column("trainee_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("proposal.id")),
        sa.Column(
            "persona_version_id", sa.Uuid(), sa.ForeignKey("config_version.id"), nullable=False
        ),
        sa.Column(
            "scenario_version_id", sa.Uuid(), sa.ForeignKey("config_version.id"), nullable=False
        ),
        sa.Column(
            "scoring_profile_version_id",
            sa.Uuid(),
            sa.ForeignKey("config_version.id"),
            nullable=False,
        ),
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

    op.create_table(
        "assessment",
        _pk(),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_no", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _enum(
                "assessment_status", "queued", "running", "needs_review", "finalized", "failed"
            ),
            nullable=False,
        ),
        sa.Column("composite", sa.Float()),
        sa.Column("band", sa.String(50)),
        sa.Column("confidence", _enum("confidence", "high", "medium", "low")),
        sa.Column("dimensions", JSON_T),
        sa.Column("details", JSON_T),
        _created(),
        sa.UniqueConstraint("session_id", "run_no"),
    )

    op.create_table(
        "assessment_evidence",
        _pk(),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("assessment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(50), nullable=False),
        sa.Column(
            "turn_id", sa.Uuid(), sa.ForeignKey("turn.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("polarity", _enum("polarity", "positive", "negative"), nullable=False),
    )

    op.create_table(
        "review",
        _pk(),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("assessment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column(
            "decision", _enum("review_decision", "approve", "override"), nullable=False
        ),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("comment", sa.Text()),
        _created(),
    )

    op.create_table(
        "report",
        _pk(),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("assessment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", _enum("report_format", "pdf", "html"), nullable=False),
        sa.Column("blob_uri", sa.String(500), nullable=False),
        _created(),
    )

    op.create_table(
        "llm_call_log",
        _pk(),
        sa.Column("ref_id", sa.Uuid()),
        sa.Column("purpose", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _created(),
    )
    op.create_index("ix_llm_call_log_ref_id", "llm_call_log", ["ref_id"])

    op.create_table(
        "audit_log",
        _pk(),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("app_user.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid()),
        sa.Column("detail", JSON_T),
        _created(),
    )


def downgrade() -> None:
    for table in (
        "audit_log",
        "llm_call_log",
        "report",
        "review",
        "assessment_evidence",
        "assessment",
        "turn",
        "session",
        "proposal_segment",
        "proposal",
        "config_version",
        "app_user",
    ):
        op.drop_table(table)
