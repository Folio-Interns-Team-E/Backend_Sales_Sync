"""add persistent workspace notifications"""
from alembic import op
from migrations.schema_compat import create_table, create_index
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261011_notifications"
down_revision = "20261011_audit_events"
branch_labels = None
depends_on = None


def upgrade():
    create_table("notifications", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("kind", sa.String(40), nullable=False), sa.Column("title", sa.String(160), nullable=False), sa.Column("body", sa.String(500), nullable=False), sa.Column("link", sa.String(255)), sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    create_index("ix_notifications_user_team_read_created", "notifications", ["user_id", "team_id", "is_read", "created_at"])


def downgrade():
    op.drop_index("ix_notifications_user_team_read_created", table_name="notifications")
    op.drop_table("notifications")
