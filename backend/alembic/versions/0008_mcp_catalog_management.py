"""Persist versioned administrator-managed MCP catalogs."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_mcp_catalog_management"
down_revision: Union[str, Sequence[str], None] = "0007_operation_job_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "mcp_catalog_configs" not in tables:
        op.create_table(
            "mcp_catalog_configs",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("draft_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("draft_secrets_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column("draft_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("published_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("published_secrets_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column("active_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_by", sa.String(length=36), nullable=True),
            sa.Column("published_by", sa.String(length=36), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if "mcp_catalog_audits" not in tables:
        op.create_table(
            "mcp_catalog_audits",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.String(length=36), nullable=True),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_mcp_catalog_audits_created_at", "mcp_catalog_audits", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "mcp_catalog_audits" in tables:
        op.drop_index("ix_mcp_catalog_audits_created_at", table_name="mcp_catalog_audits")
        op.drop_table("mcp_catalog_audits")
    if "mcp_catalog_configs" in tables:
        op.drop_table("mcp_catalog_configs")
