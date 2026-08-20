"""Persist immutable MCP PluginSet releases for durable workflow replay."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_mcp_plugin_set_releases"
down_revision: Union[str, Sequence[str], None] = "0008_mcp_catalog_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "mcp_plugin_set_releases" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "mcp_plugin_set_releases",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("catalog_json", sa.Text(), nullable=False),
        sa.Column("secrets_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("published_by", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version"),
    )
    op.create_index(
        "ix_mcp_plugin_set_releases_published_at",
        "mcp_plugin_set_releases",
        ["published_at"],
    )


def downgrade() -> None:
    if "mcp_plugin_set_releases" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index("ix_mcp_plugin_set_releases_published_at", table_name="mcp_plugin_set_releases")
    op.drop_table("mcp_plugin_set_releases")
