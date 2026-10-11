"""Add account security activity."""
from alembic import op
from migrations.schema_compat import create_table, create_index
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261003_security_events"
down_revision = "20261003_oauth_identities"
branch_labels = None
depends_on = None


def upgrade():
    create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.Enum("password_login", "password_reset", "google_login", "github_login", "google_linked", "github_linked", native_enum=False, create_constraint=True, name="security_action"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index("ix_security_events_user_created_id", "security_events", ["user_id", "created_at", "id"])


def downgrade():
    op.drop_table("security_events")
