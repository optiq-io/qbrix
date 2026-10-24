"""add loops

Revision ID: 1b8655e01617
Revises: 6002b843b626
Create Date: 2026-10-24 10:41:47.369984

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1b8655e01617"
down_revision: Union[str, None] = "6002b843b626"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "loops",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("metric_id", sa.String(length=32), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("paused_from", sa.String(length=16), nullable=True),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("fallback_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["metric_id"],
            ["metrics.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_loop_tenant_key"),
    )
    op.create_index(op.f("ix_loops_metric_id"), "loops", ["metric_id"], unique=False)
    op.create_table(
        "cycles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("loop_id", sa.String(length=32), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("engine_version", sa.String(length=16), nullable=False),
        sa.Column("metric_version_id", sa.String(length=32), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["loop_id"], ["loops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["metric_version_id"],
            ["metric_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loop_id", "number", name="uq_cycle_number"),
    )
    op.create_table(
        "loop_options",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("loop_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["loop_id"], ["loops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loop_id", "key", name="uq_loop_option_key"),
    )


def downgrade() -> None:
    op.drop_table("loop_options")
    op.drop_table("cycles")
    op.drop_index(op.f("ix_loops_metric_id"), table_name="loops")
    op.drop_table("loops")
