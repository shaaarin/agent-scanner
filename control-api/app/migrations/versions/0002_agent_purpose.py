"""agentconfig.agent_purpose

Назначение агента из формы «Конфигурации агентов». Раньше поле было в UI, но
не сохранялось, и DeepTeam генерировал атаки без описания цели.

Revision ID: 0002_agent_purpose
Revises: 0001_baseline
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_agent_purpose"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.add_column(sa.Column("agent_purpose", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.drop_column("agent_purpose")
