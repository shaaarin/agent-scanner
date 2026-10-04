"""scan.agent_config_id optional

Remote scan targets such as MCP servers do not have an AgentConfig. Agent-
backed scan types continue to enforce the relationship in their API flow.

Revision ID: 0003_optional_scan_agent_config
Revises: 0002_agent_purpose
Create Date: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_optional_scan_agent_config"
down_revision: Union[str, None] = "0002_agent_purpose"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("scan") as batch_op:
        batch_op.alter_column(
            "agent_config_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("scan") as batch_op:
        batch_op.alter_column(
            "agent_config_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
