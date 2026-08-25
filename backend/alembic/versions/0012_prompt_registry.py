"""Add platform-owned, versioned Prompt Registry tables."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012_prompt_registry"
down_revision: Union[str, Sequence[str], None] = "0011_knowledge_graph_product"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "prompt_templates" not in tables:
        op.create_table(
            "prompt_templates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("key", sa.String(64), nullable=False, unique=True),
            sa.Column("display_name", sa.String(96), nullable=False),
            sa.Column("description", sa.String(512), nullable=False, server_default=""),
            sa.Column("published_version", sa.Integer()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_prompt_templates_key", "prompt_templates", ["key"])
    if "prompt_template_versions" not in tables:
        op.create_table(
            "prompt_template_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("template_id", sa.String(36), sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("digest", sa.String(64), nullable=False),
            sa.Column("created_by_admin_id", sa.String(36)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("template_id", "version", name="uq_prompt_template_version"),
        )
        op.create_index("ix_prompt_template_versions_template_id", "prompt_template_versions", ["template_id"])


def downgrade() -> None:
    # Prompt history is audit data. Keep forward-only rollback semantics.
    pass
