"""scope Cal.com credentials to a workspace"""
from alembic import op
import sqlalchemy as sa

revision = "20261007_calcom_workspace"
down_revision = "20261007_lead_provider"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE calcom_integrations AS ci SET team_id = tm.team_id FROM team_members AS tm WHERE ci.user_id = tm.user_id AND ci.team_id IS NULL")
    op.execute("DELETE FROM calcom_integrations WHERE team_id IS NULL")
    op.execute("DELETE FROM calcom_integrations WHERE id IN (SELECT id FROM (SELECT id, row_number() OVER (PARTITION BY team_id ORDER BY updated_at DESC NULLS LAST, created_at DESC) AS row_num FROM calcom_integrations) ranked WHERE row_num > 1)")
    op.alter_column("calcom_integrations", "team_id", existing_type=sa.UUID(), nullable=False)
    op.drop_constraint("calcom_integrations_user_id_key", "calcom_integrations", type_="unique")
    op.create_unique_constraint("uq_calcom_integrations_team_id", "calcom_integrations", ["team_id"])


def downgrade():
    op.drop_constraint("uq_calcom_integrations_team_id", "calcom_integrations", type_="unique")
    op.create_unique_constraint("calcom_integrations_user_id_key", "calcom_integrations", ["user_id"])
    op.alter_column("calcom_integrations", "team_id", existing_type=sa.UUID(), nullable=True)
