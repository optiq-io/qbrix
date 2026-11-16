"""add the resolved index on alerts

Revision ID: b3d81f6c2a94
Revises: a7c2e9d14f53
Create Date: 2026-11-16 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d81f6c2a94"
down_revision: Union[str, None] = "a7c2e9d14f53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_alerts_tenant_id_resolved_at",
        "alerts",
        ["tenant_id", "resolved_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_tenant_id_resolved_at", table_name="alerts")
