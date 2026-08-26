"""Replace deprecated chunk-strategy values with supported equivalents."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_chunk_strategy_cleanup"
down_revision: Union[str, Sequence[str], None] = "0015_user_web_search_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Migrate configuration only; existing vectors are rebuilt explicitly.

    ``recursive`` and the former fake ``semantic`` mode become source-aware
    ``auto``. The former flat ``parent_child`` approximation maps to its only
    real behaviour, Markdown heading chunking. Actual chunk rows are left
    untouched until the owner requests a rebuild, avoiding an implicit costly
    re-embed during schema migration.
    """
    bind = op.get_bind()
    for table in ("kbs", "documents"):
        if table not in sa.inspect(bind).get_table_names():
            continue
        bind.execute(
            sa.text(
                f"UPDATE {table} SET chunk_strategy = 'auto' "
                "WHERE chunk_strategy IN ('recursive', 'semantic')"
            )
        )
        bind.execute(
            sa.text(
                f"UPDATE {table} SET chunk_strategy = 'markdown_heading' "
                "WHERE chunk_strategy = 'parent_child'"
            )
        )


def downgrade() -> None:
    # The old semantic/parent-child labels never represented distinct runtime
    # algorithms, so they cannot be restored faithfully. Keep safe recursive
    # compatibility if a rollback is required.
    bind = op.get_bind()
    for table in ("kbs", "documents"):
        if table not in sa.inspect(bind).get_table_names():
            continue
        bind.execute(
            sa.text(f"UPDATE {table} SET chunk_strategy = 'recursive' WHERE chunk_strategy = 'auto'")
        )
