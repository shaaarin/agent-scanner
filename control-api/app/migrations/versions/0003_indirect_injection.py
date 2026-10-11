"""injectiontrial + trafficevent injection fields

Косвенные промпт-инъекции (scanner-indirect): таблица прогонов InjectionTrial
и три поля на trafficevent (trial_id/injected/injection_target), которыми
прокси помечает перехваченный обмен в скане этого типа.

Revision ID: 0003_indirect_injection
Revises: 0002_agent_purpose
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_indirect_injection"
down_revision: Union[str, None] = "0002_agent_purpose"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("trafficevent") as batch_op:
        batch_op.add_column(sa.Column("trial_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("injected", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("injection_target", sa.String(), nullable=True))
        batch_op.create_index("ix_trafficevent_trial_id", ["trial_id"])

    op.create_table(
        "injectiontrial",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scan_id", sa.Integer(), sa.ForeignKey("scan.id"), nullable=False),
        sa.Column("baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("task_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("task", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_tool", sa.String(), nullable=True),
        sa.Column("occurrence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("mode", sa.String(), nullable=False, server_default="append"),
        sa.Column("payload_name", sa.String(), nullable=True),
        sa.Column("payload_family", sa.String(), nullable=True),
        sa.Column("payload_text", sa.Text(), nullable=True),
        sa.Column("canary", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("injected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verdict", sa.String(), nullable=True),
        sa.Column("verdict_reason", sa.Text(), nullable=True),
        sa.Column("agent_response", sa.Text(), nullable=True),
        sa.Column("baseline_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_injectiontrial_scan_id", "injectiontrial", ["scan_id"])


def downgrade() -> None:
    op.drop_index("ix_injectiontrial_scan_id", table_name="injectiontrial")
    op.drop_table("injectiontrial")
    with op.batch_alter_table("trafficevent") as batch_op:
        batch_op.drop_index("ix_trafficevent_trial_id")
        batch_op.drop_column("injection_target")
        batch_op.drop_column("injected")
        batch_op.drop_column("trial_id")
