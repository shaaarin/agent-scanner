"""assets: McpAsset, SkillAsset and Scan asset reference

Раздел «Активы»: MCP-цели и skills становятся сущностями наряду с
AgentConfig (агенты). Скан ссылается на актив парой asset_kind/asset_id;
для агентов по-прежнему заполняется agent_config_id -- его читают сканеры
и launcher. Существующие сканы помечаются как сканы агентов.

Revision ID: 0007_assets
Revises: 0006_mcp_artifacts
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_assets"
down_revision: Union[str, None] = "0006_mcp_artifacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcpasset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_mcpasset_name"),
    )
    op.create_index("ix_mcpasset_name", "mcpasset", ["name"])

    op.create_table(
        "skillasset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("git_repo_url", sa.String(), nullable=True),
        sa.Column("git_ref", sa.String(), nullable=True),
        sa.Column("git_access_token", sa.String(), nullable=True),
        sa.Column("archive_filename", sa.String(), nullable=True),
        sa.Column("archive_sha256", sa.String(), nullable=True),
        sa.Column("archive", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_skillasset_name"),
    )
    op.create_index("ix_skillasset_name", "skillasset", ["name"])
    op.create_index("ix_skillasset_archive_sha256", "skillasset", ["archive_sha256"])

    with op.batch_alter_table("scan") as batch_op:
        batch_op.add_column(sa.Column("asset_kind", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("asset_id", sa.Integer(), nullable=True))
    op.create_index("ix_scan_asset_kind", "scan", ["asset_kind"])
    op.create_index("ix_scan_asset_id", "scan", ["asset_id"])
    # Существующие сканы -- это сканы агентов.
    op.execute("UPDATE scan SET asset_kind = 'agent', asset_id = agent_config_id WHERE agent_config_id IS NOT NULL")


def downgrade() -> None:
    op.drop_index("ix_scan_asset_id", table_name="scan")
    op.drop_index("ix_scan_asset_kind", table_name="scan")
    with op.batch_alter_table("scan") as batch_op:
        batch_op.drop_column("asset_id")
        batch_op.drop_column("asset_kind")
    op.drop_index("ix_skillasset_archive_sha256", table_name="skillasset")
    op.drop_index("ix_skillasset_name", table_name="skillasset")
    op.drop_table("skillasset")
    op.drop_index("ix_mcpasset_name", table_name="mcpasset")
    op.drop_table("mcpasset")
