"""add chats table and chat_id to chat_messages

Revision ID: 20260723_multi_chat
Revises: 20260722_otp
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260723_multi_chat"
down_revision: Union[str, Sequence[str], None] = "20260722_otp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. Create chats table if it doesn't exist
    if "chats" not in existing_tables:
        op.create_table(
            "chats",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            sa.Column("team_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("chat_name", sa.String(), nullable=False, server_default="New Chat"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        )

    # 2. Add chat_id column to chat_messages if it doesn't exist
    existing_cols = {c["name"] for c in inspector.get_columns("chat_messages")}
    if "chat_id" not in existing_cols:
        op.add_column(
            "chat_messages",
            sa.Column("chat_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )

    # 3. Migrate existing messages that have no chat_id into a default chat per team
    conn.execute(
        sa.text("""
            INSERT INTO chats (id, team_id, chat_name, created_at)
            SELECT gen_random_uuid(), cm.team_id, 'Chat 1', NOW()
            FROM (SELECT DISTINCT team_id FROM chat_messages WHERE chat_id IS NULL) cm
            ON CONFLICT DO NOTHING
        """)
    )
    conn.execute(
        sa.text("""
            UPDATE chat_messages SET chat_id = (
                SELECT c.id FROM chats c WHERE c.team_id = chat_messages.team_id LIMIT 1
            ) WHERE chat_id IS NULL
        """)
    )

    # 4. Make chat_id non-nullable now that all rows have a value
    conn.execute(sa.text("""
        ALTER TABLE chat_messages ALTER COLUMN chat_id SET NOT NULL
    """))

    # 5. Create index if it doesn't exist
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("chat_messages")}
    if "ix_chat_messages_chat_id" not in existing_indexes:
        op.create_index("ix_chat_messages_chat_id", "chat_messages", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_chat_id", table_name="chat_messages")
    op.drop_column("chat_messages", "chat_id")
    op.drop_table("chats")
