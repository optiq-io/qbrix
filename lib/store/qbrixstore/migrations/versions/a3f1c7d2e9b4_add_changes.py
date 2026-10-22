"""add changes

Revision ID: a3f1c7d2e9b4
Revises: 7ef23ac950ca
Create Date: 2026-10-22 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a3f1c7d2e9b4"
down_revision: Union[str, None] = "7ef23ac950ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "changes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=True),
        sa.Column("client_name", sa.String(length=128), nullable=True),
        sa.Column("api_key_id", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("learning", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("undoes_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["undoes_id"], ["changes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_changes_tenant_id_target_created_at",
        "changes",
        ["tenant_id", "target_type", "target_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_changes_tenant_id_target_created_at", table_name="changes")
    op.drop_table("changes")
