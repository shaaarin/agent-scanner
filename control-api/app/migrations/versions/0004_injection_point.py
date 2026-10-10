"""injectiontrial.injection_point

Дискриминатор места инъекции на прогоне: tool_result (indirect_injection,
прежнее поведение) или system_prompt (system_prompt_leak). Старые строки
получают дефолт tool_result.

Revision ID: 0004_injection_point
Revises: 0003_indirect_injection
Create Date: 2026-10-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_injection_point"
down_revision: Union[str, None] = "0003_indirect_injection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("injectiontrial") as batch_op:
        batch_op.add_column(
            sa.Column("injection_point", sa.String(), nullable=False, server_default="tool_result")
        )


def downgrade() -> None:
    with op.batch_alter_table("injectiontrial") as batch_op:
        batch_op.drop_column("injection_point")
