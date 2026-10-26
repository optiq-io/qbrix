"""add loops live_since

Revision ID: 28298f88ba0d
Revises: 1b8655e01617
Create Date: 2026-10-26 17:31:15.871948

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "28298f88ba0d"
down_revision: Union[str, None] = "1b8655e01617"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "loops", sa.Column("live_since", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE loops SET live_since = ("
        "SELECT max(cycles.started_at) FROM cycles WHERE cycles.loop_id = loops.id"
        ") WHERE state <> 'draft'"
    )


def downgrade() -> None:
    op.drop_column("loops", "live_since")
