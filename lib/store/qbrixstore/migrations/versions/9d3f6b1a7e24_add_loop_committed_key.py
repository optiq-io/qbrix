"""add the option a committed loop serves

Revision ID: 9d3f6b1a7e24
Revises: e4b1d8a27c60
Create Date: 2026-11-09 20:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d3f6b1a7e24"
down_revision: Union[str, None] = "e4b1d8a27c60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "loops", sa.Column("committed_key", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("loops", "committed_key")
