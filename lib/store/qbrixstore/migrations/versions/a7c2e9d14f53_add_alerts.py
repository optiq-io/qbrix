"""add alerts: safety pauses and warnings, open until they end

Revision ID: a7c2e9d14f53
Revises: b5d3f81c2e64
Create Date: 2026-11-15 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c2e9d14f53"
down_revision: Union[str, None] = "b5d3f81c2e64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("loop_id", sa.String(length=32), nullable=False),
        sa.Column("cycle_id", sa.String(length=32), nullable=True),
        sa.Column("signal", sa.String(length=32), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clear_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=16), nullable=True),
        sa.Column("resolved_kind", sa.String(length=16), nullable=True),
        sa.Column("resolved_user_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["loop_id"], ["loops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alerts_tenant_id_opened_at",
        "alerts",
        ["tenant_id", "opened_at", "id"],
    )
    op.create_index(
        "uq_alerts_open",
        "alerts",
        ["loop_id", "signal"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_open", table_name="alerts")
    op.drop_index("ix_alerts_tenant_id_opened_at", table_name="alerts")
    op.drop_table("alerts")
