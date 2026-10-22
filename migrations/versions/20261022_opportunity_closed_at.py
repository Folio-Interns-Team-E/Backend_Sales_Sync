"""track opportunity close timestamps

Revision ID: 20261022_closed_at
Revises: 20261019_plans
"""

from alembic import op
import sqlalchemy as sa


revision = "20261022_closed_at"
down_revision = "20261019_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("opportunities", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE opportunities SET closed_at = updated_at WHERE stage IN ('Closed Won', 'Closed Lost')")
    op.create_index("ix_opportunities_closed_at", "opportunities", ["closed_at"])


def downgrade():
    op.drop_index("ix_opportunities_closed_at", table_name="opportunities")
    op.drop_column("opportunities", "closed_at")
