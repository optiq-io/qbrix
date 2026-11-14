"""add which context properties a loop's engine learns from

Revision ID: b5d3f81c2e64
Revises: e2a9c5d4f817
Create Date: 2026-11-12 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5d3f81c2e64"
down_revision: Union[str, None] = "e2a9c5d4f817"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("loops", sa.Column("context_schema", sa.JSON(), nullable=True))
    op.add_column("cycles", sa.Column("context_schema", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("cycles", "context_schema")
    op.drop_column("loops", "context_schema")
