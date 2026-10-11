"""add workspace api keys"""
from alembic import op
from migrations.schema_compat import create_table, create_index
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261011_workspace_api_keys"
down_revision = "20261011_notifications"
branch_labels = None
depends_on = None


def upgrade():
    create_table("workspace_api_keys", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False), sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(100), nullable=False), sa.Column("key_prefix", sa.String(20), nullable=False), sa.Column("key_hash", sa.String(64), nullable=False, unique=True), sa.Column("last_used_at", sa.DateTime(timezone=True)), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    create_index("ix_workspace_api_keys_team_active", "workspace_api_keys", ["team_id", "revoked_at", "expires_at"])


def downgrade():
    op.drop_index("ix_workspace_api_keys_team_active", table_name="workspace_api_keys")
    op.drop_table("workspace_api_keys")
