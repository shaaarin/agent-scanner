"""Link retry attempts without replacing historical scans or reports."""
from alembic import op
import sqlalchemy as sa

revision = "0011_scan_retries"
down_revision = "0010_mcp_scan_statuses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scan") as batch:
        batch.add_column(sa.Column("retry_of_scan_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("retry_root_scan_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("retry_mode", sa.String(), nullable=True))
        batch.create_foreign_key("fk_scan_retry_of", "scan", ["retry_of_scan_id"], ["id"])
        batch.create_foreign_key("fk_scan_retry_root", "scan", ["retry_root_scan_id"], ["id"])
        batch.create_index("ix_scan_retry_of_scan_id", ["retry_of_scan_id"])
        batch.create_index("ix_scan_retry_root_scan_id", ["retry_root_scan_id"])


def downgrade() -> None:
    with op.batch_alter_table("scan") as batch:
        batch.drop_index("ix_scan_retry_root_scan_id")
        batch.drop_index("ix_scan_retry_of_scan_id")
        batch.drop_constraint("fk_scan_retry_root", type_="foreignkey")
        batch.drop_constraint("fk_scan_retry_of", type_="foreignkey")
        batch.drop_column("retry_mode")
        batch.drop_column("retry_root_scan_id")
        batch.drop_column("retry_of_scan_id")
