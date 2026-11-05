"""One-time invite links for joining an organization."""
from alembic import op
import sqlalchemy as sa

revision = "0014_invites"
down_revision = "0013_org_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="reader"),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_by_user_id", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_invites_org_id", "invites", ["org_id"])
    op.create_index("ix_invites_token", "invites", ["token"], unique=True)
    op.create_foreign_key("fk_invite_org", "invites", "organizations", ["org_id"], ["id"])
    op.create_foreign_key("fk_invite_created_by", "invites", "users", ["created_by_user_id"], ["id"])
    op.create_foreign_key("fk_invite_used_by", "invites", "users", ["used_by_user_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_invite_used_by", "invites", type_="foreignkey")
    op.drop_constraint("fk_invite_created_by", "invites", type_="foreignkey")
    op.drop_constraint("fk_invite_org", "invites", type_="foreignkey")
    op.drop_index("ix_invites_token", table_name="invites")
    op.drop_index("ix_invites_org_id", table_name="invites")
    op.drop_table("invites")
