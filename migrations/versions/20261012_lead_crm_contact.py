"""Link converted prospects to CRM contacts without removing lead history."""

from alembic import op
import sqlalchemy as sa

revision = "20261012_lead_crm_contact"
down_revision = "20261011_google_calendar_meetings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("leads", sa.Column("crm_contact_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_leads_crm_contact_id", "leads", "contacts", ["crm_contact_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_leads_crm_contact_id", "leads", ["crm_contact_id"])


def downgrade():
    op.drop_index("ix_leads_crm_contact_id", table_name="leads")
    op.drop_constraint("fk_leads_crm_contact_id", "leads", type_="foreignkey")
    op.drop_column("leads", "crm_contact_id")
