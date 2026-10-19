"""rename paid subscription tiers to plus and pro

Revision ID: 20261019_plans
Revises: 6f2efeef68f7
"""

from alembic import op

revision = "20261019_plans"
down_revision = "20261016_account_mfa"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE teams SET subscription_tier = 'plus' WHERE subscription_tier = 'growth'")
    op.execute("UPDATE teams SET subscription_tier = 'pro' WHERE subscription_tier = 'enterprise'")
    op.execute("UPDATE subscriptions SET tier = 'plus' WHERE tier = 'growth'")
    op.execute("UPDATE subscriptions SET tier = 'pro' WHERE tier = 'enterprise'")


def downgrade():
    op.execute("UPDATE teams SET subscription_tier = 'growth' WHERE subscription_tier = 'plus'")
    op.execute("UPDATE teams SET subscription_tier = 'enterprise' WHERE subscription_tier = 'pro'")
    op.execute("UPDATE subscriptions SET tier = 'growth' WHERE tier = 'plus'")
    op.execute("UPDATE subscriptions SET tier = 'enterprise' WHERE tier = 'pro'")
