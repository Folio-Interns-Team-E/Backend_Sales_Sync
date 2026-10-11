"""support repeat sequence enrollment runs"""
from alembic import op
import sqlalchemy as sa

revision = "20261011_enrollment_runs"
down_revision = "20261010_email_suppressions"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    unique_names = {item["name"] for item in inspector.get_unique_constraints("sequence_enrollments")}
    if "uq_sequence_lead_enrollment" in unique_names:
        op.drop_constraint("uq_sequence_lead_enrollment", "sequence_enrollments", type_="unique")
    columns = {column["name"]: column for column in inspector.get_columns("sequence_enrollments")}
    if "reply_override" not in columns:
        op.add_column("sequence_enrollments", sa.Column("reply_override", sa.Boolean(), server_default=sa.false(), nullable=False))
    indexes = {item["name"]: item for item in inspector.get_indexes("sequence_enrollments")}
    if "ix_sequence_enrollment_lead" not in indexes:
        op.create_index("ix_sequence_enrollment_lead", "sequence_enrollments", ["sequence_id", "lead_id"])
    elif indexes["ix_sequence_enrollment_lead"]["column_names"] != ["sequence_id", "lead_id"]:
        raise RuntimeError("Existing sequence enrollment index has unexpected columns")
    delivery_columns = {column["name"]: column for column in inspector.get_columns("sequence_deliveries")}
    if delivery_columns["step_id"]["nullable"] is False:
        op.alter_column("sequence_deliveries", "step_id", existing_type=sa.UUID(), nullable=True)
    foreign_keys = {item["name"]: item for item in inspector.get_foreign_keys("sequence_deliveries")}
    step_fk = foreign_keys.get("sequence_deliveries_step_id_fkey")
    if step_fk and step_fk.get("options", {}).get("ondelete") != "SET NULL":
        op.drop_constraint("sequence_deliveries_step_id_fkey", "sequence_deliveries", type_="foreignkey")
        step_fk = None
    if not step_fk:
        op.create_foreign_key("sequence_deliveries_step_id_fkey", "sequence_deliveries", "sequence_steps", ["step_id"], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint("sequence_deliveries_step_id_fkey", "sequence_deliveries", type_="foreignkey")
    op.execute("DELETE FROM sequence_deliveries WHERE step_id IS NULL")
    op.alter_column("sequence_deliveries", "step_id", existing_type=sa.UUID(), nullable=False)
    op.create_foreign_key("sequence_deliveries_step_id_fkey", "sequence_deliveries", "sequence_steps", ["step_id"], ["id"], ondelete="CASCADE")
    op.drop_index("ix_sequence_enrollment_lead", table_name="sequence_enrollments")
    op.drop_column("sequence_enrollments", "reply_override")
    op.create_unique_constraint("uq_sequence_lead_enrollment", "sequence_enrollments", ["sequence_id", "lead_id"])
