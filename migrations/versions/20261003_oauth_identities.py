"""Add provider identities without changing existing users."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261003_oauth_identities"
down_revision = "6f2efeef68f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "oauth_identities",
        sa.Column("provider", sa.String(16), primary_key=True),
        sa.Column("subject", sa.String(255), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
    )
    op.create_index("ix_oauth_identities_user_id", "oauth_identities", ["user_id"])


def downgrade():
    op.drop_table("oauth_identities")
