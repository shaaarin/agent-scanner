"""Attach every existing row to an organization.

`organization_id` appears on all owned resources (LLM models, agent configs,
MCP assets, skill assets, MCPB artifacts, scans). A bootstrap organization
"Основная" is created and takes all pre-existing rows, so the column can be
NOT NULL afterwards: nothing is dropped, the base just gets an owner.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_org_columns"
down_revision = "0012_auth_tables"
branch_labels = None
depends_on = None

# table -> (index name, FK name)
_TABLES = {
    "llmmodel": ("ix_llmmodel_organization_id", "fk_llmmodel_org"),
    "agentconfig": ("ix_agentconfig_organization_id", "fk_agentconfig_org"),
    "mcpasset": ("ix_mcpasset_organization_id", "fk_mcpasset_org"),
    "skillasset": ("ix_skillasset_organization_id", "fk_skillasset_org"),
    "mcpartifact": ("ix_mcpartifact_organization_id", "fk_mcpartifact_org"),
    "scan": ("ix_scan_organization_id", "fk_scan_org"),
}

BOOTSTRAP_ORG_NAME = "Основная организация"


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "INSERT INTO organizations (name, description, created_at) "
            "VALUES (:name, NULL, NOW()) RETURNING id"
        ).bindparams(name=BOOTSTRAP_ORG_NAME)
    )
    org_id = result.scalar_one()
    for table in _TABLES:
        bind.execute(sa.text(f"UPDATE {table} SET organization_id = :org_id").bindparams(org_id=org_id))

    for table, (index_name, fk_name) in _TABLES.items():
        with op.batch_alter_table(table) as batch:
            batch.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        op.create_index(index_name, table, ["organization_id"])
        op.create_foreign_key(fk_name, table, "organizations", ["organization_id"], ["id"])


def downgrade() -> None:
    for table, (index_name, fk_name) in _TABLES.items():
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.drop_index(index_name, table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("organization_id")
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM organizations WHERE name = :name").bindparams(name=BOOTSTRAP_ORG_NAME))
