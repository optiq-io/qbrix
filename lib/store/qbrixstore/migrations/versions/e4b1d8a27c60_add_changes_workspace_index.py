"""add the workspace index on changes

Revision ID: e4b1d8a27c60
Revises: 7c2e9a41d3b6
Create Date: 2026-10-31 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b1d8a27c60"
down_revision: Union[str, None] = "7c2e9a41d3b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_changes_tenant_id_created_at",
        "changes",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_changes_tenant_id_created_at", table_name="changes")
