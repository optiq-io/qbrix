"""add change approvals

Revision ID: c7a4e2d91b38
Revises: b5e83c1f9a42
Create Date: 2026-11-11 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a4e2d91b38"
down_revision: Union[str, None] = "b5e83c1f9a42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("changes", sa.Column("level", sa.String(length=8), nullable=True))
    op.add_column("changes", sa.Column("proposal", sa.JSON(), nullable=True))
    op.add_column(
        "changes", sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "changes",
        sa.Column("decided_by_user_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "changes", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "changes", sa.Column("decided_in", sa.String(length=128), nullable=True)
    )
    op.add_column("changes", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.create_index(
        "uq_changes_waiting",
        "changes",
        ["tenant_id", "target_type", "target_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'waiting'"),
    )


def downgrade() -> None:
    op.drop_index("uq_changes_waiting", table_name="changes")
    op.drop_column("changes", "decision_reason")
    op.drop_column("changes", "decided_in")
    op.drop_column("changes", "decided_at")
    op.drop_column("changes", "decided_by_user_id")
    op.drop_column("changes", "asked_at")
    op.drop_column("changes", "proposal")
    op.drop_column("changes", "level")
