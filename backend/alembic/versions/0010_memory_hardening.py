"""Add provenance and lifecycle fields for durable user memory."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010_memory_hardening"
down_revision: Union[str, Sequence[str], None] = "0009_mcp_plugin_set_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_memories" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("user_memories")}
    additions = (
        ("extractor_model", sa.String(length=128), True, None),
        ("extractor_version", sa.String(length=64), True, None),
        ("last_accessed_at", sa.DateTime(timezone=True), True, None),
        ("recall_count", sa.Integer(), False, "0"),
    )
    for name, column_type, nullable, server_default in additions:
        if name not in columns:
            op.add_column(
                "user_memories",
                sa.Column(name, column_type, nullable=nullable, server_default=server_default),
            )
    indexes = {index["name"] for index in inspector.get_indexes("user_memories")}
    if "ix_user_memories_active_scope_capacity" not in indexes:
        op.create_index(
            "ix_user_memories_active_scope_capacity",
            "user_memories",
            ["user_id", "status", "scope", "scope_id", "importance", "updated_at"],
        )


def downgrade() -> None:
    # The fields are additive audit data.  Dropping them would discard memory
    # provenance and lifecycle history, so this migration intentionally has no
    # destructive downgrade.
    pass
