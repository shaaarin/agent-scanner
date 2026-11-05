"""Users, organizations and memberships for password-based access control."""
from alembic import op
import sqlalchemy as sa

revision = "0012_auth_tables"
down_revision = "0011_scan_retries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("login", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_login", "users", ["login"], unique=True)

    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_organizations_name", "organizations", ["name"])
    op.create_foreign_key("fk_org_created_by", "organizations", "users", ["created_by_user_id"], ["id"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="reader"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
    op.create_foreign_key("fk_membership_user", "memberships", "users", ["user_id"], ["id"])
    op.create_foreign_key("fk_membership_org", "memberships", "organizations", ["org_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_membership_org", "memberships", type_="foreignkey")
    op.drop_constraint("fk_membership_user", "memberships", type_="foreignkey")
    op.drop_index("ix_memberships_org_id", table_name="memberships")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_constraint("fk_org_created_by", "organizations", type_="foreignkey")
    op.drop_index("ix_organizations_name", table_name="organizations")
    op.drop_table("organizations")
    op.drop_index("ix_users_login", table_name="users")
    op.drop_table("users")
