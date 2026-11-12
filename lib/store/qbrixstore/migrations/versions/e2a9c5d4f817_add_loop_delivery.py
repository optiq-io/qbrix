"""add who a loop decides for

Revision ID: e2a9c5d4f817
Revises: c7a4e2d91b38
Create Date: 2026-11-12 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a9c5d4f817"
down_revision: Union[str, None] = "c7a4e2d91b38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "loops",
        sa.Column("delivery", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.alter_column("loops", "delivery", server_default=None)


def downgrade() -> None:
    op.drop_column("loops", "delivery")
