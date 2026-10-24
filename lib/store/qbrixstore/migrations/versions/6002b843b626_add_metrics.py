"""add metrics

Revision ID: 6002b843b626
Revises: a3f1c7d2e9b4
Create Date: 2026-10-24 10:11:02.610690

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6002b843b626"
down_revision: Union[str, None] = "a3f1c7d2e9b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metrics",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("score_lo", sa.Float(), nullable=True),
        sa.Column("score_hi", sa.Float(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_metric_tenant_name"),
    )
    op.create_table(
        "metric_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("metric_id", sa.String(length=32), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("minor", sa.Integer(), nullable=False),
        sa.Column("semantic", sa.Text(), nullable=False),
        sa.Column("window_sec", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["metric_id"], ["metrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "metric_id", "major", "minor", name="uq_metric_version_number"
        ),
    )


def downgrade() -> None:
    op.drop_table("metric_versions")
    op.drop_table("metrics")
