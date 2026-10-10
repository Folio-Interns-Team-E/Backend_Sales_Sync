"""add CRM accounts contacts and tasks"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_crm_foundation"
down_revision = "20261010_opportunities"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("domain", sa.String(255)), sa.Column("industry", sa.String(120)), sa.Column("employee_count", sa.String(50)), sa.Column("annual_revenue", sa.Numeric(16, 2)), sa.Column("country", sa.String(100)), sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_accounts_team_name", "accounts", ["team_id", "name"])
    op.create_table("contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("account_id", postgresql.UUID(as_uuid=True)), sa.Column("owner_id", postgresql.UUID(as_uuid=True)),
        sa.Column("first_name", sa.String(100), nullable=False), sa.Column("last_name", sa.String(100), server_default="", nullable=False), sa.Column("email", sa.String(320)), sa.Column("phone", sa.String(50)), sa.Column("job_title", sa.String(150)), sa.Column("lifecycle_stage", sa.String(40), server_default="Lead", nullable=False), sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_contacts_team_email", "contacts", ["team_id", "email"])
    op.create_table("sales_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("contact_id", postgresql.UUID(as_uuid=True)), sa.Column("opportunity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("title", sa.String(240), nullable=False), sa.Column("task_type", sa.String(30), server_default="Follow-up", nullable=False), sa.Column("priority", sa.String(20), server_default="Medium", nullable=False), sa.Column("status", sa.String(20), server_default="Open", nullable=False), sa.Column("due_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_sales_tasks_team_owner_status", "sales_tasks", ["team_id", "owner_id", "status"])


def downgrade():
    op.drop_index("ix_sales_tasks_team_owner_status", table_name="sales_tasks"); op.drop_table("sales_tasks")
    op.drop_index("ix_contacts_team_email", table_name="contacts"); op.drop_table("contacts")
    op.drop_index("ix_accounts_team_name", table_name="accounts"); op.drop_table("accounts")
