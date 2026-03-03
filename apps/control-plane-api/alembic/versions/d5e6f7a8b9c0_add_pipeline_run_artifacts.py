"""add pipeline_run_artifacts table

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-02-24

Stores JSON artifacts produced by pipeline runs (e.g. inventory summaries).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_run_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("artifact_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_run_artifacts_run_id_created_at",
        "pipeline_run_artifacts",
        ["run_id", "created_at"],
    )
    op.create_index(
        "ix_pipeline_run_artifacts_tenant_id_created_at",
        "pipeline_run_artifacts",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_pipeline_run_artifacts_run_id_artifact_type",
        "pipeline_run_artifacts",
        ["run_id", "artifact_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_run_artifacts_run_id_artifact_type", table_name="pipeline_run_artifacts")
    op.drop_index("ix_pipeline_run_artifacts_tenant_id_created_at", table_name="pipeline_run_artifacts")
    op.drop_index("ix_pipeline_run_artifacts_run_id_created_at", table_name="pipeline_run_artifacts")
    op.drop_table("pipeline_run_artifacts")

