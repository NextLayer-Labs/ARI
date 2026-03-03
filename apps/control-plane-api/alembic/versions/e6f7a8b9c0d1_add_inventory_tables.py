"""add raw ingest and canonical inventory tables

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-03-01

Adds pipeline_run_raw_ingests and canonical_inventory_items for inventory snapshot workflows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_run_raw_ingests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("facility_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("mapping_version", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_run_raw_ingests_run_id_fetched_at",
        "pipeline_run_raw_ingests",
        ["run_id", "fetched_at"],
    )
    op.create_index(
        "ix_pipeline_run_raw_ingests_tenant_facility_fetched_at",
        "pipeline_run_raw_ingests",
        ["tenant_id", "facility_id", "fetched_at"],
    )

    op.create_table(
        "canonical_inventory_items",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("facility_id", sa.String(length=36), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("on_hand", sa.Integer(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=True),
        sa.Column("reserved", sa.Integer(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("source_provider", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "facility_id", "sku"),
    )
    op.create_index(
        "ix_canonical_inventory_items_tenant_facility",
        "canonical_inventory_items",
        ["tenant_id", "facility_id"],
    )
    op.create_index(
        "ix_canonical_inventory_items_facility_sku",
        "canonical_inventory_items",
        ["facility_id", "sku"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_inventory_items_facility_sku", table_name="canonical_inventory_items")
    op.drop_index("ix_canonical_inventory_items_tenant_facility", table_name="canonical_inventory_items")
    op.drop_table("canonical_inventory_items")

    op.drop_index(
        "ix_pipeline_run_raw_ingests_tenant_facility_fetched_at",
        table_name="pipeline_run_raw_ingests",
    )
    op.drop_index(
        "ix_pipeline_run_raw_ingests_run_id_fetched_at",
        table_name="pipeline_run_raw_ingests",
    )
    op.drop_table("pipeline_run_raw_ingests")

