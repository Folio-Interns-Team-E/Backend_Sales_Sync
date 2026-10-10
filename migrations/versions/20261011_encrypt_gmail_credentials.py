"""encrypt stored Gmail refresh tokens"""
from alembic import op
import sqlalchemy as sa

from app.core.crypto import decrypt_key, encrypt_key

revision = "20261011_encrypt_gmail_credentials"
down_revision = "20261011_enrollment_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("google_credentials", sa.Column("encrypted_refresh_token", sa.String(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, refresh_token FROM google_credentials")).mappings().all()
    for row in rows:
        connection.execute(
            sa.text("UPDATE google_credentials SET encrypted_refresh_token = :token WHERE id = :id"),
            {"token": encrypt_key(row["refresh_token"]), "id": row["id"]},
        )
    op.alter_column("google_credentials", "encrypted_refresh_token", nullable=False)
    op.drop_column("google_credentials", "refresh_token")


def downgrade():
    op.add_column("google_credentials", sa.Column("refresh_token", sa.String(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, encrypted_refresh_token FROM google_credentials")).mappings().all()
    for row in rows:
        connection.execute(
            sa.text("UPDATE google_credentials SET refresh_token = :token WHERE id = :id"),
            {"token": decrypt_key(row["encrypted_refresh_token"]), "id": row["id"]},
        )
    op.alter_column("google_credentials", "refresh_token", nullable=False)
    op.drop_column("google_credentials", "encrypted_refresh_token")
