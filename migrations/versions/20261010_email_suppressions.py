"""add email suppression list"""
from alembic import op
from migrations.schema_compat import create_table, create_index
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_email_suppressions"
down_revision = "20261010_sequence_deliveries"
branch_labels = None
depends_on = None


def upgrade():
    create_table(
        "email_suppressions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("source", sa.String(40), server_default="Gmail", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("team_id", "email", name="uq_email_suppression_team_email"),
    )
    create_index("ix_email_suppression_lookup", "email_suppressions", ["team_id", "email"])


def downgrade():
    op.drop_index("ix_email_suppression_lookup", table_name="email_suppressions")
    op.drop_table("email_suppressions")
