"""add workspace audit events"""
from alembic import op
from migrations.schema_compat import create_table, create_index
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261011_audit_events"
down_revision = "20261011_encrypt_gmail_credentials"
branch_labels = None
depends_on = None


def upgrade():
    create_table("audit_events", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False), sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("action", sa.String(80), nullable=False), sa.Column("target_type", sa.String(40), nullable=False), sa.Column("target_id", sa.String(100)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    create_index("ix_audit_events_team_created_id", "audit_events", ["team_id", "created_at", "id"])


def downgrade():
    op.drop_index("ix_audit_events_team_created_id", table_name="audit_events")
    op.drop_table("audit_events")
