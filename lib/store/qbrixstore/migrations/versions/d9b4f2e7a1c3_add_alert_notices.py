"""add alert notices, the outbox of the workspace webhook

Revision ID: d9b4f2e7a1c3
Revises: c7e2a9d4b1f8
Create Date: 2026-11-25 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9b4f2e7a1c3"
down_revision: Union[str, None] = "c7e2a9d4b1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_notices",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("alert_id", sa.String(length=32), nullable=False),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["delivery_id"], ["webhook_deliveries.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_notices_unsent",
        "alert_notices",
        ["tenant_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("delivery_id IS NULL"),
        sqlite_where=sa.text("delivery_id IS NULL"),
    )
    op.create_index(
        "ix_webhook_deliveries_unfinished",
        "webhook_deliveries",
        ["tenant_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'failing')"),
        sqlite_where=sa.text("status IN ('pending', 'failing')"),
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_unfinished", table_name="webhook_deliveries")
    op.drop_index("ix_alert_notices_unsent", table_name="alert_notices")
    op.drop_table("alert_notices")
