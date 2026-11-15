"""Add canonical trainee IDs to Pod C ownership records.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainee",
        sa.Column("trainee_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint("trainee_id", name="pk_trainee"),
    )

    with op.batch_alter_table("profile") as batch:
        batch.add_column(sa.Column("trainee_id", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_profile_trainee_id_trainee", "trainee", ["trainee_id"], ["trainee_id"]
        )
    op.create_index("ix_profile_trainee_id", "profile", ["trainee_id"])

    with op.batch_alter_table("session") as batch:
        batch.add_column(sa.Column("trainee_id", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_session_trainee_id_trainee", "trainee", ["trainee_id"], ["trainee_id"]
        )
    op.create_index("ix_session_trainee_id", "session", ["trainee_id"])


def downgrade() -> None:
    op.drop_index("ix_session_trainee_id", table_name="session")
    with op.batch_alter_table("session") as batch:
        batch.drop_constraint("fk_session_trainee_id_trainee", type_="foreignkey")
        batch.drop_column("trainee_id")

    op.drop_index("ix_profile_trainee_id", table_name="profile")
    with op.batch_alter_table("profile") as batch:
        batch.drop_constraint("fk_profile_trainee_id_trainee", type_="foreignkey")
        batch.drop_column("trainee_id")

    op.drop_table("trainee")
