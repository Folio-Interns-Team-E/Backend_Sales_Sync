"""add knowledge base rag tables and fields

Revision ID: 20260715_kb_rag
Revises: dd3ea42e946e
Create Date: 2026-07-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260715_kb_rag"
down_revision: Union[str, Sequence[str], None] = "dd3ea42e946e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    asset_columns = {column["name"] for column in inspector.get_columns("knowledge_assets")}
    if "source_url" not in asset_columns:
        op.add_column("knowledge_assets", sa.Column("source_url", sa.String(), nullable=True))
    if "status" not in asset_columns:
        op.add_column(
            "knowledge_assets",
            sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'processing'")),
        )
    if "embedding_id" not in asset_columns:
        op.add_column("knowledge_assets", sa.Column("embedding_id", sa.String(), nullable=True))
    if "chunk_count" not in asset_columns:
        op.add_column(
            "knowledge_assets",
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    if "indexed_at" not in asset_columns:
        op.add_column("knowledge_assets", sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True))
    if "processing_error" not in asset_columns:
        op.add_column("knowledge_assets", sa.Column("processing_error", sa.Text(), nullable=True))

    if not inspector.has_table("knowledge_asset_chunks"):
        op.create_table(
            "knowledge_asset_chunks",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("team_id", sa.UUID(), nullable=False),
            sa.Column("asset_id", sa.UUID(), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("pinecone_vector_id", sa.String(), nullable=False),
            sa.Column("token_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("knowledge_asset_chunks")} if inspector.has_table("knowledge_asset_chunks") else set()
    if inspector.has_table("knowledge_asset_chunks"):
        if op.f("ix_knowledge_asset_chunks_asset_id") not in existing_indexes:
            op.create_index(op.f("ix_knowledge_asset_chunks_asset_id"), "knowledge_asset_chunks", ["asset_id"], unique=False)
        if op.f("ix_knowledge_asset_chunks_team_id") not in existing_indexes:
            op.create_index(op.f("ix_knowledge_asset_chunks_team_id"), "knowledge_asset_chunks", ["team_id"], unique=False)
        if op.f("ix_knowledge_asset_chunks_pinecone_vector_id") not in existing_indexes:
            op.create_index(op.f("ix_knowledge_asset_chunks_pinecone_vector_id"), "knowledge_asset_chunks", ["pinecone_vector_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("knowledge_asset_chunks"):
        existing_indexes = {index["name"] for index in inspector.get_indexes("knowledge_asset_chunks")}
        if op.f("ix_knowledge_asset_chunks_team_id") in existing_indexes:
            op.drop_index(op.f("ix_knowledge_asset_chunks_team_id"), table_name="knowledge_asset_chunks")
        if op.f("ix_knowledge_asset_chunks_asset_id") in existing_indexes:
            op.drop_index(op.f("ix_knowledge_asset_chunks_asset_id"), table_name="knowledge_asset_chunks")
        if op.f("ix_knowledge_asset_chunks_pinecone_vector_id") in existing_indexes:
            op.drop_index(op.f("ix_knowledge_asset_chunks_pinecone_vector_id"), table_name="knowledge_asset_chunks")
        op.drop_table("knowledge_asset_chunks")

    asset_columns = {column["name"] for column in inspector.get_columns("knowledge_assets")}
    for column_name in ["processing_error", "indexed_at", "chunk_count", "embedding_id", "status", "source_url"]:
        if column_name in asset_columns:
            op.drop_column("knowledge_assets", column_name)