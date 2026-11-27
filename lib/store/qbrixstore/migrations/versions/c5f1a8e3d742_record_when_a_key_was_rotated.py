"""record when a key was rotated

Revision ID: c5f1a8e3d742
Revises: a4e7c2d9f136
Create Date: 2026-11-27 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5f1a8e3d742"
down_revision: Union[str, None] = "a4e7c2d9f136"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "rotated_at")
