"""Add per-user web-search engine overrides."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0015_user_web_search_settings"
down_revision: Union[str, Sequence[str], None] = "0014_prompt_registry_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``0000_schema_bootstrap`` creates new databases from current ORM
    # metadata, so a fresh install already has these fields. Existing
    # deployments arriving from revision 0014 need the two additive columns.
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("users")
    }
    if "web_search_provider" not in columns:
        op.add_column("users", sa.Column("web_search_provider", sa.String(length=32), nullable=True))
    if "web_search_api_key_enc" not in columns:
        op.add_column("users", sa.Column("web_search_api_key_enc", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "web_search_api_key_enc")
    op.drop_column("users", "web_search_provider")
