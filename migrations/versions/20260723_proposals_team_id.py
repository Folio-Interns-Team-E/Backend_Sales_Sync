"""add team_id to proposals

Revision ID: 20260723_proposals_team_id
Revises: 20260723_multi_chat
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260723_proposals_team_id"
down_revision: Union[str, Sequence[str], None] = "20260723_multi_chat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_cols = {c["name"] for c in inspector.get_columns("proposals")}

    if "team_id" not in existing_cols:
        op.add_column(
            "proposals",
            sa.Column("team_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )

        # Backfill from leads.team_id
        conn.execute(sa.text("""
            UPDATE proposals SET team_id = (
                SELECT l.team_id FROM leads l WHERE l.id = proposals.lead_id
            ) WHERE team_id IS NULL AND lead_id IS NOT NULL
        """))

        # Delete any proposals that couldn't be backfilled (no lead)
        conn.execute(sa.text("DELETE FROM proposals WHERE team_id IS NULL"))

        # Make non-nullable
        conn.execute(sa.text("ALTER TABLE proposals ALTER COLUMN team_id SET NOT NULL"))

        # Create index
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("proposals")}
        if "ix_proposals_team_id" not in existing_indexes:
            op.create_index("ix_proposals_team_id", "proposals", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_proposals_team_id", table_name="proposals")
    op.drop_column("proposals", "team_id")
