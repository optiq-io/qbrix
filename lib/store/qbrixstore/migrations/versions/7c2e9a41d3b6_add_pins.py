"""add pins

Revision ID: 7c2e9a41d3b6
Revises: fc715410e081
Create Date: 2026-10-31 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7c2e9a41d3b6"
down_revision: Union[str, None] = "fc715410e081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pins",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", "ref", name="uq_pin_user_kind_ref"),
    )
    op.create_index(op.f("ix_pins_tenant_id"), "pins", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pins_tenant_id"), table_name="pins")
    op.drop_table("pins")
