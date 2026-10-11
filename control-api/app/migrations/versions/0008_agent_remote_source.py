"""remote agents: AgentConfig.source + remote address/token

Новый источник агента remote: уже запущенный вне платформы сервис, который
не собирается через launcher. Для него git-поля не обязательны, вместо них
задаются remote_base_url и remote_token; взаимодействие -- как раньше, через
api_config/langgraph_config. Существующие агенты -- repository.

Revision ID: 0008_agent_remote_source
Revises: 0007_assets
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_agent_remote_source"
down_revision: Union[str, None] = "0007_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(), nullable=False, server_default="repository")
        )
        batch_op.add_column(sa.Column("remote_base_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("remote_headers", sa.JSON(), nullable=True))
        # remote-агенту репозиторий не нужен.
        batch_op.alter_column("git_repo_url", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.alter_column("git_repo_url", existing_type=sa.String(), nullable=False)
        batch_op.drop_column("remote_headers")
        batch_op.drop_column("remote_base_url")
        batch_op.drop_column("source")
