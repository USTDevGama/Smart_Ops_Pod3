"""trim to the 5 tables we use now

Drops app_user, assessment, assessment_evidence, review, report, llm_call_log and audit_log,
plus the scoring-profile setting. session.trainee_id and proposal.owner_id (links to app_user)
become plain text columns trainee_ref and owner_ref holding the login user.

One-way: there is no downgrade, because the dropped tables hold nothing we could restore.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. add the new text columns, filled from the old user rows
    op.add_column("session", sa.Column("trainee_ref", sa.String(64)))
    op.add_column("proposal", sa.Column("owner_ref", sa.String(64)))
    op.execute(
        "UPDATE session SET trainee_ref = "
        "(SELECT idp_sub FROM app_user WHERE app_user.id = session.trainee_id)"
    )
    op.execute(
        "UPDATE proposal SET owner_ref = "
        "(SELECT idp_sub FROM app_user WHERE app_user.id = proposal.owner_id)"
    )

    # 2. swap the columns (batch mode so this also works on SQLite)
    with op.batch_alter_table("session") as batch:
        batch.drop_column("trainee_id")
        batch.drop_column("scoring_profile_version_id")
        batch.alter_column("trainee_ref", existing_type=sa.String(64), nullable=False)
        batch.create_index("ix_session_trainee_ref", ["trainee_ref"])
    with op.batch_alter_table("proposal") as batch:
        batch.drop_column("owner_id")
        batch.alter_column("owner_ref", existing_type=sa.String(64), nullable=False)
        batch.create_index("ix_proposal_owner_ref", ["owner_ref"])

    # 3. nothing points at the scoring settings any more
    op.execute("DELETE FROM config_version WHERE kind = 'scoring_profile'")

    # 4. drop the tables, children first
    for table in (
        "report",
        "review",
        "assessment_evidence",
        "assessment",
        "llm_call_log",
        "audit_log",
        "app_user",
    ):
        op.drop_table(table)


def downgrade() -> None:
    raise NotImplementedError("0002 drops tables and cannot be undone; restore from a backup")
