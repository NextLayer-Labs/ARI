"""add canonical returns table

Revision ID: f0a1b2c3d4e5
Revises: e6f7a8b9c0d1
Create Date: 2026-04-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_return_items",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("facility_id", sa.String(length=36), nullable=False),
        sa.Column("return_id", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("created_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disposition", sa.Text(), nullable=True),
        sa.Column("source_provider", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("tenant_id", "facility_id", "return_id"),
    )
    op.create_index(
        "ix_canonical_return_items_tenant_facility",
        "canonical_return_items",
        ["tenant_id", "facility_id"],
    )
    op.create_index(
        "ix_canonical_return_items_facility_status",
        "canonical_return_items",
        ["facility_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_return_items_facility_status", table_name="canonical_return_items")
    op.drop_index("ix_canonical_return_items_tenant_facility", table_name="canonical_return_items")
    op.drop_table("canonical_return_items")
