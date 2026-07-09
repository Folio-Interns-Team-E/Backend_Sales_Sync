"""add stripe subscription fields to teams

Revision ID: 20260709_stripe
Revises: 
Create Date: 2026-07-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260709_stripe"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("stripe_customer_id", sa.String(), nullable=True))
    op.add_column("teams", sa.Column("stripe_subscription_id", sa.String(), nullable=True))
    op.add_column(
        "teams",
        sa.Column("subscription_tier", sa.String(), nullable=False, server_default=sa.text("'free'")),
    )
    op.add_column(
        "teams",
        sa.Column("subscription_status", sa.String(), nullable=False, server_default=sa.text("'active'")),
    )
    op.add_column("teams", sa.Column("subscription_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_teams_stripe_customer_id", "teams", ["stripe_customer_id"])
    op.create_unique_constraint("uq_teams_stripe_subscription_id", "teams", ["stripe_subscription_id"])


def downgrade() -> None:
    op.drop_constraint("uq_teams_stripe_subscription_id", "teams", type_="unique")
    op.drop_constraint("uq_teams_stripe_customer_id", "teams", type_="unique")
    op.drop_column("teams", "subscription_ends_at")
    op.drop_column("teams", "subscription_status")
    op.drop_column("teams", "subscription_tier")
    op.drop_column("teams", "stripe_subscription_id")
    op.drop_column("teams", "stripe_customer_id")
