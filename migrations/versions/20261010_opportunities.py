"""add opportunities pipeline"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_opportunities"
down_revision = "20261009_calcom_oauth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("stage", sa.String(length=32), server_default="Prospecting", nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("probability", sa.Integer(), server_default="10", nullable=False),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("loss_reason", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_opportunities_amount_nonnegative"),
        sa.CheckConstraint("probability >= 0 AND probability <= 100", name="ck_opportunities_probability_range"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_opportunities_team_stage", "opportunities", ["team_id", "stage"])
    op.create_index("ix_opportunities_team_owner", "opportunities", ["team_id", "owner_id"])


def downgrade():
    op.drop_index("ix_opportunities_team_owner", table_name="opportunities")
    op.drop_index("ix_opportunities_team_stage", table_name="opportunities")
    op.drop_table("opportunities")
