"""Add per-user Google Calendar credentials and meeting links."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261011_google_calendar_meetings"
down_revision = "20261011_user_profile_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "google_calendar_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_email", sa.String(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_google_calendar_credentials_user_id", "google_calendar_credentials", ["user_id"], unique=True)
    op.add_column("meetings", sa.Column("calendar_provider", sa.String(), nullable=True))
    op.add_column("meetings", sa.Column("meet_url", sa.String(), nullable=True))
    op.add_column("meetings", sa.Column("duration_minutes", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("meetings", "duration_minutes")
    op.drop_column("meetings", "meet_url")
    op.drop_column("meetings", "calendar_provider")
    op.drop_index("ix_google_calendar_credentials_user_id", table_name="google_calendar_credentials")
    op.drop_table("google_calendar_credentials")
