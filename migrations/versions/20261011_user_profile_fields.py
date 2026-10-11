"""Store user-specific company and job title."""

from alembic import op
import sqlalchemy as sa

revision = "20261011_user_profile_fields"
down_revision = "20261011_invite_code_expiry"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("company", sa.String(length=160), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.String(length=120), nullable=True))


def downgrade():
    op.drop_column("users", "job_title")
    op.drop_column("users", "company")
