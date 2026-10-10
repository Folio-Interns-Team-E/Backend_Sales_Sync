"""add outreach sequences"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="20261010_sequences"; down_revision="20261010_crm_foundation"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("sequences", sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("team_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("teams.id",ondelete="CASCADE"),nullable=False),sa.Column("owner_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),sa.Column("name",sa.String(200),nullable=False),sa.Column("status",sa.String(20),server_default="Draft",nullable=False),sa.Column("timezone",sa.String(80),server_default="Asia/Karachi",nullable=False),sa.Column("daily_limit",sa.Integer(),server_default="40",nullable=False),sa.Column("stop_on_reply",sa.Boolean(),server_default=sa.true(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index("ix_sequences_team_status","sequences",["team_id","status"])
    op.create_table("sequence_steps",sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("sequence_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("sequences.id",ondelete="CASCADE"),nullable=False),sa.Column("position",sa.Integer(),nullable=False),sa.Column("delay_days",sa.Integer(),server_default="0",nullable=False),sa.Column("subject",sa.String(300),nullable=False),sa.Column("body",sa.Text(),nullable=False),sa.UniqueConstraint("sequence_id","position",name="uq_sequence_step_position"))
    op.create_table("sequence_enrollments",sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("sequence_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("sequences.id",ondelete="CASCADE"),nullable=False),sa.Column("lead_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("leads.id",ondelete="CASCADE"),nullable=False),sa.Column("owner_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),sa.Column("status",sa.String(20),server_default="Active",nullable=False),sa.Column("current_step",sa.Integer(),server_default="0",nullable=False),sa.Column("next_send_at",sa.DateTime(timezone=True)),sa.Column("last_sent_at",sa.DateTime(timezone=True)),sa.Column("enrolled_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column("completed_at",sa.DateTime(timezone=True)),sa.UniqueConstraint("sequence_id","lead_id",name="uq_sequence_lead_enrollment"))
    op.create_index("ix_sequence_enrollment_due","sequence_enrollments",["status","next_send_at"])

def downgrade():
    op.drop_index("ix_sequence_enrollment_due",table_name="sequence_enrollments");op.drop_table("sequence_enrollments");op.drop_table("sequence_steps");op.drop_index("ix_sequences_team_status",table_name="sequences");op.drop_table("sequences")
