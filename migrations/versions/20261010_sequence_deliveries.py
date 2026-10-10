"""add sequence delivery tracking"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_sequence_deliveries"
down_revision = "20261010_sequences"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sequence_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sequence_enrollments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sequence_steps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), server_default="Processing", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("enrollment_id", "step_id", name="uq_sequence_delivery_step"),
    )
    op.create_index("ix_sequence_delivery_daily", "sequence_deliveries", ["sequence_id", "status", "sent_at"])


def downgrade():
    op.drop_index("ix_sequence_delivery_daily", table_name="sequence_deliveries")
    op.drop_table("sequence_deliveries")
