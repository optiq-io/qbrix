"""add connection levels

Revision ID: b5e83c1f9a42
Revises: 9d3f6b1a7e24
Create Date: 2026-11-11 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e83c1f9a42"
down_revision: Union[str, None] = "9d3f6b1a7e24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connection_levels",
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("connection_id", "kind"),
    )


def downgrade() -> None:
    op.drop_table("connection_levels")
