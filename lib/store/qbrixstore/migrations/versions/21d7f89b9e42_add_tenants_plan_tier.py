"""add tenants.plan_tier

Revision ID: 21d7f89b9e42
Revises: 16b4e197aa18
Create Date: 2026-07-28 17:15:28.119511

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "21d7f89b9e42"
down_revision: Union[str, None] = "16b4e197aa18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # temporary server_default so the not-null add succeeds on existing rows,
    # dropped below so the schema matches the model, which relies on the
    # python-side default. env.py sets compare_server_default, so leaving it in
    # place would report as drift.
    op.add_column(
        "tenants",
        sa.Column(
            "plan_tier",
            sa.String(length=32),
            nullable=False,
            server_default="free",
        ),
    )

    # an active subscription is the entitlement authority: real stripe rows for
    # paying tenants, internal- prefixed rows for comped ones, which is how
    # set-plan-tier.sh provisions them. anything not backed by an active
    # subscription is free. subscriptions.tenant_id is unique, so this matches
    # at most one row per tenant.
    op.execute("""
        UPDATE tenants t
           SET plan_tier = s.plan_tier
          FROM subscriptions s
         WHERE s.tenant_id = t.id
           AND s.status = 'active'
        """)

    op.alter_column("tenants", "plan_tier", server_default=None)


def downgrade() -> None:
    op.drop_column("tenants", "plan_tier")
