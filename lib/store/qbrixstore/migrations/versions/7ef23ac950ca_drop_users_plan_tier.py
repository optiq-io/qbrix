"""drop users.plan_tier

Revision ID: 7ef23ac950ca
Revises: 21d7f89b9e42
Create Date: 2026-08-19 16:42:48.359239

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7ef23ac950ca"
down_revision: Union[str, None] = "21d7f89b9e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # the tier has been read off tenants since 21d7f89b9e42, and nothing writes
    # it any more. every row's value was a duplicate of its tenant's.
    op.drop_column("users", "plan_tier")


def downgrade() -> None:
    # temporary server_default so the not-null add succeeds on existing rows,
    # dropped below so the schema matches the model, which relies on the
    # python-side default. env.py sets compare_server_default, so leaving it in
    # place would report as drift. same shape as 21d7f89b9e42.
    #
    # the original per-tenant values are not recoverable; every row lands on
    # 'free'. acceptable because nothing reads this column — tenants.plan_tier
    # is the authority and is untouched here.
    op.add_column(
        "users",
        sa.Column(
            "plan_tier",
            sa.String(length=32),
            nullable=False,
            server_default="free",
        ),
    )
    op.alter_column("users", "plan_tier", server_default=None)
