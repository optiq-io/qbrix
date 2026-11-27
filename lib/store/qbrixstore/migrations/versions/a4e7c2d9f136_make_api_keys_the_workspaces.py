"""make api keys the workspace's, per app and environment

Revision ID: a4e7c2d9f136
Revises: b8d3e6f1a2c9
Create Date: 2026-11-27 20:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4e7c2d9f136"
down_revision: Union[str, None] = "b8d3e6f1a2c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("tenant_id", sa.String(32), nullable=True))
    op.add_column("api_keys", sa.Column("created_by_id", sa.String(32), nullable=True))
    op.add_column("api_keys", sa.Column("app", sa.String(255), nullable=True))
    op.add_column("api_keys", sa.Column("environment", sa.String(64), nullable=True))

    op.execute("""
        UPDATE api_keys k
           SET tenant_id = u.tenant_id,
               created_by_id = k.user_id,
               app = k.name,
               environment = 'production'
          FROM users u
         WHERE u.id = k.user_id
        """)

    op.alter_column("api_keys", "tenant_id", nullable=False)
    op.alter_column("api_keys", "app", nullable=False)
    op.alter_column("api_keys", "environment", nullable=False)

    op.create_foreign_key(
        "api_keys_tenant_id_fkey", "api_keys", "tenants", ["tenant_id"], ["id"]
    )
    op.create_foreign_key(
        "api_keys_created_by_id_fkey",
        "api_keys",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_api_keys_tenant_id_is_active", "api_keys", ["tenant_id", "is_active"]
    )

    op.drop_constraint("api_keys_user_id_fkey", "api_keys", type_="foreignkey")
    op.alter_column("api_keys", "user_id", nullable=True)
    op.create_foreign_key(
        "api_keys_user_id_fkey",
        "api_keys",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # a key whose creator is gone has no owner to return to; before this
    # revision it was deleted with them.
    op.execute("DELETE FROM api_keys WHERE user_id IS NULL")

    op.drop_constraint("api_keys_user_id_fkey", "api_keys", type_="foreignkey")
    op.alter_column("api_keys", "user_id", nullable=False)
    op.create_foreign_key(
        "api_keys_user_id_fkey", "api_keys", "users", ["user_id"], ["id"]
    )

    op.drop_index("ix_api_keys_tenant_id_is_active", table_name="api_keys")
    op.drop_constraint("api_keys_created_by_id_fkey", "api_keys", type_="foreignkey")
    op.drop_constraint("api_keys_tenant_id_fkey", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "environment")
    op.drop_column("api_keys", "app")
    op.drop_column("api_keys", "created_by_id")
    op.drop_column("api_keys", "tenant_id")
