"""baseline schema

Establishes the full schema as it stood when Alembic was introduced. This is
a frozen snapshot (explicit `create_table` calls, not live metadata) so later
migrations stack cleanly on top of it on a fresh install.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llmmodel",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_llmmodel_name"),
    )

    op.create_table(
        "agentconfig",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("git_repo_url", sa.String(), nullable=False),
        sa.Column("git_ref", sa.String(), nullable=False),
        sa.Column("git_access_token", sa.String(), nullable=True),
        sa.Column("dockerfile_path", sa.String(), nullable=False),
        sa.Column("env_example_path", sa.String(), nullable=True),
        sa.Column("api_port", sa.Integer(), nullable=True),
        sa.Column("entrypoint", sa.JSON(), nullable=True),
        sa.Column("env_vars", sa.JSON(), nullable=False),
        sa.Column("resources", sa.JSON(), nullable=True),
        sa.Column("interaction_mode", sa.String(), nullable=False),
        sa.Column("api_config", sa.JSON(), nullable=True),
        sa.Column("langgraph_config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_agentconfig_name"),
    )

    op.create_table(
        "scan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("agent_config_id", sa.Integer(), sa.ForeignKey("agentconfig.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("phase", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("agent_namespace", sa.String(), nullable=True),
        sa.Column("agent_pod_name", sa.String(), nullable=True),
        sa.Column("build_job_name", sa.String(), nullable=True),
        sa.Column("built_image", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_scan_name", "scan", ["name"])
    op.create_index("ix_scan_agent_config_id", "scan", ["agent_config_id"])
    op.create_index("ix_scan_session_id", "scan", ["session_id"])

    op.create_table(
        "scanlog",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scan_id", sa.Integer(), sa.ForeignKey("scan.id"), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=True),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_scanlog_scan_id", "scanlog", ["scan_id"])

    op.create_table(
        "trafficevent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=True),
        sa.Column("flow_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("raw_excerpt", sa.Text(), nullable=False),
        sa.Column("upstream_base_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_trafficevent_session_id", "trafficevent", ["session_id"])
    op.create_index("ix_trafficevent_flow_id", "trafficevent", ["flow_id"])


def downgrade() -> None:
    op.drop_table("trafficevent")
    op.drop_table("scanlog")
    op.drop_table("scan")
    op.drop_table("agentconfig")
    op.drop_table("llmmodel")
