"""add otp columns to users

Revision ID: 20260722_otp
Revises: 20260715_kb_rag
Create Date: 2026-07-22 14:55:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260722_otp"
down_revision: Union[str, Sequence[str], None] = "20260715_kb_rag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("otp", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "otp_expires_at")
    op.drop_column("users", "otp")
