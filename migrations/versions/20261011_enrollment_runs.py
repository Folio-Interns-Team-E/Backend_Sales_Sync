"""support repeat sequence enrollment runs"""
from alembic import op
import sqlalchemy as sa

revision = "20261011_enrollment_runs"
down_revision = "20261010_email_suppressions"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_sequence_lead_enrollment", "sequence_enrollments", type_="unique")
    op.add_column("sequence_enrollments", sa.Column("reply_override", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_index("ix_sequence_enrollment_lead", "sequence_enrollments", ["sequence_id", "lead_id"])
    op.drop_constraint("sequence_deliveries_step_id_fkey", "sequence_deliveries", type_="foreignkey")
    op.alter_column("sequence_deliveries", "step_id", existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key("sequence_deliveries_step_id_fkey", "sequence_deliveries", "sequence_steps", ["step_id"], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint("sequence_deliveries_step_id_fkey", "sequence_deliveries", type_="foreignkey")
    op.execute("DELETE FROM sequence_deliveries WHERE step_id IS NULL")
    op.alter_column("sequence_deliveries", "step_id", existing_type=sa.UUID(), nullable=False)
    op.create_foreign_key("sequence_deliveries_step_id_fkey", "sequence_deliveries", "sequence_steps", ["step_id"], ["id"], ondelete="CASCADE")
    op.drop_index("ix_sequence_enrollment_lead", table_name="sequence_enrollments")
    op.drop_column("sequence_enrollments", "reply_override")
    op.create_unique_constraint("uq_sequence_lead_enrollment", "sequence_enrollments", ["sequence_id", "lead_id"])
