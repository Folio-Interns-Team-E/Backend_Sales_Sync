"""Expire workspace invite codes after thirty days."""

from alembic import op
import sqlalchemy as sa

revision = "20261011_invite_code_expiry"
down_revision = "20261011_logout_all_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "teams",
        sa.Column(
            "invite_code_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(now() + interval '30 days')"),
        ),
    )


def downgrade():
    op.drop_column("teams", "invite_code_expires_at")
