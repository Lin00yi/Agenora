"""Record Prompt Registry provenance on rolling conversation summaries."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013_conversation_summary_prompt_trace"
down_revision: Union[str, Sequence[str], None] = "0012_prompt_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "conversation_summaries" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("conversation_summaries")}
    if "summary_prompt_key" not in columns:
        op.add_column("conversation_summaries", sa.Column("summary_prompt_key", sa.String(64)))
    if "summary_prompt_version" not in columns:
        op.add_column("conversation_summaries", sa.Column("summary_prompt_version", sa.Integer()))
    if "summary_prompt_digest" not in columns:
        op.add_column("conversation_summaries", sa.Column("summary_prompt_digest", sa.String(64)))


def downgrade() -> None:
    # Summary provenance is audit data. Keep forward-only rollback semantics.
    pass
