"""add indexes on foreign keys and hot filter columns

Revision ID: 16b4e197aa18
Revises: 6cc60423ca2b
Create Date: 2026-07-28 16:40:17.611120

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "16b4e197aa18"
down_revision: Union[str, None] = "6cc60423ca2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# plain CREATE INDEX, not CONCURRENTLY: these tables are small, so the brief
# ACCESS EXCLUSIVE lock is sub-second, and staying inside the transaction the
# migration runner opens keeps the revision atomic and safe to retry. a failed
# CONCURRENTLY build would instead leave an INVALID index behind and wedge the
# helm pre-upgrade hook's retry on "relation already exists".
_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_arms_pool_id", "arms", ["pool_id"]),
    ("ix_experiments_pool_id", "experiments", ["pool_id"]),
    ("ix_experiments_meta_experiment_id", "experiments", ["meta_experiment_id"]),
    ("ix_experiments_tenant_id_enabled", "experiments", ["tenant_id", "enabled"]),
    ("ix_feature_gates_default_arm_id", "feature_gates", ["default_arm_id"]),
    ("ix_users_tenant_id", "users", ["tenant_id"]),
    ("ix_api_keys_user_id_is_active", "api_keys", ["user_id", "is_active"]),
    ("ix_invites_invited_by", "invites", ["invited_by"]),
    (
        "ix_invites_tenant_id_status_expires_at",
        "invites",
        ["tenant_id", "status", "expires_at"],
    ),
    ("ix_invoices_tenant_id", "invoices", ["tenant_id"]),
]


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
