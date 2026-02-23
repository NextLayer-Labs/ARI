"""add retry lineage columns to pipeline_runs

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-02-21

Adds retry_of_run_id and root_run_id for queryable retry lineage.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipeline_runs",
        sa.Column("retry_of_run_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "pipeline_runs",
        sa.Column("root_run_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "idx_pipeline_runs_retry_of_run_id",
        "pipeline_runs",
        ["retry_of_run_id"],
        unique=False,
    )
    op.create_index(
        "idx_pipeline_runs_root_run_id",
        "pipeline_runs",
        ["root_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_pipeline_runs_retry_of_run_id",
        "pipeline_runs",
        "pipeline_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_pipeline_runs_root_run_id",
        "pipeline_runs",
        "pipeline_runs",
        ["root_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_pipeline_runs_root_run_id",
        "pipeline_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_pipeline_runs_retry_of_run_id",
        "pipeline_runs",
        type_="foreignkey",
    )
    op.drop_index("idx_pipeline_runs_root_run_id", table_name="pipeline_runs")
    op.drop_index("idx_pipeline_runs_retry_of_run_id", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "root_run_id")
    op.drop_column("pipeline_runs", "retry_of_run_id")
