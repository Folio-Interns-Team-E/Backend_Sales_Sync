"""add Cal.com OAuth credentials"""
from alembic import op
import sqlalchemy as sa

revision = "20261009_calcom_oauth"
down_revision = "20261007_calcom_workspace"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calcom_integrations", sa.Column("credential_type", sa.String(length=16), server_default="api_key", nullable=False))
    op.add_column("calcom_integrations", sa.Column("encrypted_access_token", sa.String(), nullable=True))
    op.add_column("calcom_integrations", sa.Column("encrypted_refresh_token", sa.String(), nullable=True))
    op.add_column("calcom_integrations", sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("calcom_integrations", "encrypted_api_key", existing_type=sa.String(), nullable=True)
    op.alter_column("calcom_integrations", "event_type_id", existing_type=sa.String(), nullable=True)


def downgrade():
    op.execute("DELETE FROM calcom_integrations WHERE encrypted_api_key IS NULL OR event_type_id IS NULL")
    op.alter_column("calcom_integrations", "event_type_id", existing_type=sa.String(), nullable=False)
    op.alter_column("calcom_integrations", "encrypted_api_key", existing_type=sa.String(), nullable=False)
    op.drop_column("calcom_integrations", "token_expires_at")
    op.drop_column("calcom_integrations", "encrypted_refresh_token")
    op.drop_column("calcom_integrations", "encrypted_access_token")
    op.drop_column("calcom_integrations", "credential_type")
