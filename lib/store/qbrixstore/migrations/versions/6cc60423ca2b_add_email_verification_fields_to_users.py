"""add email verification fields to users

Revision ID: 6cc60423ca2b
Revises: d5c0368ed54b
Create Date: 2026-06-30 10:07:52.068172

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6cc60423ca2b"
down_revision: Union[str, None] = "d5c0368ed54b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # add email_verified with a temporary server_default so the not-null backfill
    # succeeds on existing rows, then grandfather all pre-existing users as
    # verified (they predate verification and must not be locked out of login),
    # then drop the server_default so the schema matches the model (which relies
    # on the application-side python default of False for new inserts).
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE users SET email_verified = true, email_verified_at = now()")
    op.alter_column("users", "email_verified", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
