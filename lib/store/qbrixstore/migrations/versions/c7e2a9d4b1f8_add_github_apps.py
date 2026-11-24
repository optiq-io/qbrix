"""add the workspace's github app

Revision ID: c7e2a9d4b1f8
Revises: f3a8c61d2e57
Create Date: 2026-11-24 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e2a9d4b1f8"
down_revision: Union[str, None] = "f3a8c61d2e57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_apps",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("app_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("owner_type", sa.String(length=16), nullable=False),
        sa.Column("private_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("webhook_secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("events_token", sa.String(length=64), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
        sa.UniqueConstraint("events_token"),
    )


def downgrade() -> None:
    op.drop_table("github_apps")
