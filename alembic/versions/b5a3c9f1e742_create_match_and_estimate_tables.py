"""create match and estimate tables

Revision ID: b5a3c9f1e742
Revises: caacee657823
Create Date: 2026-09-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5a3c9f1e742"
down_revision: Union[str, Sequence[str], None] = "caacee657823"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "takeoff_item_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("takeoff_item_id", sa.Integer(), nullable=False),
        sa.Column("catalog_product_id", sa.Integer(), nullable=True),
        sa.Column("product_code", sa.String(length=255), nullable=True),
        sa.Column("product_name", sa.String(length=255), nullable=True),
        sa.Column("catalog_unit", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="review",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_takeoff_item_matches_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["takeoff_item_id"],
            ["takeoff_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "takeoff_item_id",
            name="uq_takeoff_item_matches_takeoff_item_id",
        ),
    )

    op.create_table(
        "estimates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column(
            "labor_total",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
            server_default="0.0000",
        ),
        sa.Column(
            "material_total",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
            server_default="0.0000",
        ),
        sa.Column(
            "misc_total",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
            server_default="0.0000",
        ),
        sa.Column(
            "grand_total",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
            server_default="0.0000",
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="completed",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["takeoff_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_estimates_job_id"),
    )

    op.create_table(
        "estimate_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("takeoff_item_id", sa.Integer(), nullable=False),
        sa.Column("catalog_product_id", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(length=255), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
        ),
        sa.Column(
            "labor_unit_cost",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
        ),
        sa.Column(
            "material_unit_cost",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
        ),
        sa.Column(
            "misc_unit_cost",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
        ),
        sa.Column(
            "labor_total",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
        ),
        sa.Column(
            "material_total",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
        ),
        sa.Column(
            "misc_total",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
        ),
        sa.Column(
            "line_total",
            sa.Numeric(precision=19, scale=4),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["estimate_id"],
            ["estimates.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["takeoff_item_id"],
            ["takeoff_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "estimate_id",
            "takeoff_item_id",
            name="uq_estimate_items_estimate_takeoff_item",
        ),
    )
    op.create_index(
        "ix_estimate_items_estimate_id",
        "estimate_items",
        ["estimate_id"],
        unique=False,
    )
    op.create_index(
        "ix_estimate_items_takeoff_item_id",
        "estimate_items",
        ["takeoff_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_estimate_items_takeoff_item_id",
        table_name="estimate_items",
    )
    op.drop_index(
        "ix_estimate_items_estimate_id",
        table_name="estimate_items",
    )
    op.drop_table("estimate_items")
    op.drop_table("estimates")
    op.drop_table("takeoff_item_matches")
