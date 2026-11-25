"""add github mentions and deliveries

Revision ID: b8d3e6f1a2c9
Revises: d9b4f2e7a1c3
Create Date: 2026-11-25 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d3e6f1a2c9"
down_revision: Union[str, None] = "d9b4f2e7a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_mentions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("loop_id", sa.String(length=32), nullable=False),
        sa.Column("repository", sa.String(length=140), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("sha", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_by", sa.String(length=255), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "loop_id", "repository", "kind", "ref", name="uq_github_mention"
        ),
    )
    op.create_index(
        "ix_github_mentions_loop_at",
        "github_mentions",
        ["tenant_id", "loop_id", "at", "id"],
    )
    op.create_index(
        "ix_github_mentions_repository",
        "github_mentions",
        ["tenant_id", "repository"],
    )
    op.create_table(
        "github_deliveries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_github_deliveries_received_at", "github_deliveries", ["received_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_github_deliveries_received_at", table_name="github_deliveries")
    op.drop_table("github_deliveries")
    op.drop_index("ix_github_mentions_repository", table_name="github_mentions")
    op.drop_index("ix_github_mentions_loop_at", table_name="github_mentions")
    op.drop_table("github_mentions")
