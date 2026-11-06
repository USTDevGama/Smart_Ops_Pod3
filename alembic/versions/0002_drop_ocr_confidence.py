"""drop proposal_segment.ocr_confidence: ingestion no longer does OCR

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("proposal_segment") as batch:
        batch.drop_column("ocr_confidence")


def downgrade() -> None:
    with op.batch_alter_table("proposal_segment") as batch:
        batch.add_column(sa.Column("ocr_confidence", sa.Float(), nullable=True))
