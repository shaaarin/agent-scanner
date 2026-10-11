"""store MCPB artifacts in SQLite

Revision ID: 0006_mcp_artifacts
Revises: 0005_optional_scan_agent_config
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_mcp_artifacts"
down_revision: Union[str, None] = "0005_optional_scan_agent_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcpartifact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_mcpartifact_sha256", "mcpartifact", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_mcpartifact_sha256", table_name="mcpartifact")
    op.drop_table("mcpartifact")
