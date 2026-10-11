"""scope Cal.com credentials to a workspace"""
from alembic import op
import sqlalchemy as sa

revision = "20261007_calcom_workspace"
down_revision = "20261007_lead_provider"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns("calcom_integrations")}
    if "team_id" not in columns:
        raise RuntimeError("calcom_integrations.team_id is missing; reconcile this table manually")
    op.execute("UPDATE calcom_integrations AS ci SET team_id = tm.team_id FROM team_members AS tm WHERE ci.user_id = tm.user_id AND ci.team_id IS NULL")
    missing = connection.execute(sa.text("SELECT count(*) FROM calcom_integrations WHERE team_id IS NULL")).scalar_one()
    duplicates = connection.execute(sa.text("SELECT count(*) FROM (SELECT team_id FROM calcom_integrations GROUP BY team_id HAVING count(*) > 1) AS duplicate_teams")).scalar_one()
    if missing or duplicates:
        raise RuntimeError(f"Cal.com workspace migration needs manual review: {missing} unassigned and {duplicates} duplicate teams; no rows were deleted")
    if columns["team_id"]["nullable"]:
        op.alter_column("calcom_integrations", "team_id", existing_type=sa.UUID(), nullable=False)
    constraints = inspector.get_unique_constraints("calcom_integrations")
    for constraint in constraints:
        if constraint["column_names"] == ["user_id"]:
            op.drop_constraint(constraint["name"], "calcom_integrations", type_="unique")
    if not any(constraint["column_names"] == ["team_id"] for constraint in constraints):
        op.create_unique_constraint("uq_calcom_integrations_team_id", "calcom_integrations", ["team_id"])


def downgrade():
    op.drop_constraint("uq_calcom_integrations_team_id", "calcom_integrations", type_="unique")
    op.create_unique_constraint("calcom_integrations_user_id_key", "calcom_integrations", ["user_id"])
    op.alter_column("calcom_integrations", "team_id", existing_type=sa.UUID(), nullable=True)
