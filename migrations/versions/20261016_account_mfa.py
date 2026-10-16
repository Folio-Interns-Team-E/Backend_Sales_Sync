"""Add authenticator MFA and recovery-code storage."""

from alembic import op
import sqlalchemy as sa

revision = "20261016_account_mfa"
down_revision = "20261012_lead_crm_contact"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("mfa_recovery_code_hashes", sa.Text(), nullable=True))
    op.drop_constraint("security_action", "security_events", type_="check")
    op.create_check_constraint(
        "security_action",
        "security_events",
        "action IN ('password_login', 'password_reset', 'google_login', 'github_login', 'google_linked', 'github_linked', 'logout_all', 'mfa_enabled', 'mfa_disabled', 'mfa_login', 'mfa_recovery_regenerated')",
    )


def downgrade():
    op.execute("DELETE FROM security_events WHERE action IN ('mfa_enabled', 'mfa_disabled', 'mfa_login', 'mfa_recovery_regenerated')")
    op.drop_constraint("security_action", "security_events", type_="check")
    op.create_check_constraint(
        "security_action",
        "security_events",
        "action IN ('password_login', 'password_reset', 'google_login', 'github_login', 'google_linked', 'github_linked', 'logout_all')",
    )
    op.drop_column("users", "mfa_recovery_code_hashes")
    op.drop_column("users", "mfa_secret_encrypted")
    op.drop_column("users", "mfa_enabled")
