"""Support immediate account-wide session revocation."""

from alembic import op
import sqlalchemy as sa

revision = "20261011_logout_all_sessions"
down_revision = "20261011_workspace_api_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("session_version", sa.Integer(), server_default="0", nullable=False))
    op.drop_constraint("security_action", "security_events", type_="check")
    op.create_check_constraint(
        "security_action",
        "security_events",
        "action IN ('password_login', 'password_reset', 'google_login', 'github_login', 'google_linked', 'github_linked', 'logout_all')",
    )


def downgrade():
    op.execute("DELETE FROM security_events WHERE action = 'logout_all'")
    op.drop_constraint("security_action", "security_events", type_="check")
    op.create_check_constraint(
        "security_action",
        "security_events",
        "action IN ('password_login', 'password_reset', 'google_login', 'github_login', 'google_linked', 'github_linked')",
    )
    op.drop_column("users", "session_version")
