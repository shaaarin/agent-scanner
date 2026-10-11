"""MCP asset deploy settings (optional, for dynamic scanning)

Необязательный блок deploy у MCP-актива: как поднять сервер из
репозитория/MCPB для динамического сканирования (порт, команда, env).
На форму и хранение не влияет ни один существующий движок -- это данные
под грядущий деплой, пусто по умолчанию.

Revision ID: 0009_mcp_asset_deploy
Revises: 0008_agent_remote_source
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_mcp_asset_deploy"
down_revision: Union[str, None] = "0008_agent_remote_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("mcpasset") as batch_op:
        batch_op.add_column(sa.Column("deploy", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("mcpasset") as batch_op:
        batch_op.drop_column("deploy")
