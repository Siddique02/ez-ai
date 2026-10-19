"""create takeoff item edits table

Revision ID: d7e2a91c4f06
Revises: b5a3c9f1e742
Create Date: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e2a91c4f06"
down_revision: Union[str, Sequence[str], None] = "b5a3c9f1e742"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "takeoff_item_edits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("takeoff_item_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["takeoff_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_takeoff_item_edits_job_id",
        "takeoff_item_edits",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_takeoff_item_edits_takeoff_item_id",
        "takeoff_item_edits",
        ["takeoff_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_takeoff_item_edits_takeoff_item_id",
        table_name="takeoff_item_edits",
    )
    op.drop_index(
        "ix_takeoff_item_edits_job_id",
        table_name="takeoff_item_edits",
    )
    op.drop_table("takeoff_item_edits")
