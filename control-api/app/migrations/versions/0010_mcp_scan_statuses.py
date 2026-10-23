"""Allow MCP success/partially_failed without rewriting historical reports."""
from alembic import op
import sqlalchemy as sa

revision = "0010_mcp_scan_statuses"
down_revision = "0009_mcp_asset_deploy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline uses VARCHAR (ORM persists enum member names, in uppercase).
    # Also accommodate older VARCHAR(9) schemas created by SQLModel.
    with op.batch_alter_table("scan") as batch:
        batch.alter_column("status", existing_type=sa.String(), type_=sa.String(32), existing_nullable=False)


def downgrade() -> None:
    # Older application versions cannot deserialize these enum members.
    op.execute("UPDATE scan SET status = 'COMPLETED' WHERE status IN ('SUCCESS', 'PARTIALLY_FAILED')")
    with op.batch_alter_table("scan") as batch:
        batch.alter_column("status", existing_type=sa.String(32), type_=sa.String(), existing_nullable=False)
