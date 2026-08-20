"""Separate explicit KB pins from automatic per-turn routing.

Historical non-null ``conversations.kb_id`` values are preserved as explicit
pins. New conversations default to automatic routing and never persist a
router's one-turn selection.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_conversation_kb_mode"
down_revision: Union[str, Sequence[str], None] = "0003_kb_eval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "conversations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("conversations")}
    if "kb_mode" not in columns:
        op.add_column(
            "conversations",
            sa.Column("kb_mode", sa.String(length=16), nullable=False, server_default="auto"),
        )
    op.execute("UPDATE conversations SET kb_mode = 'pinned' WHERE kb_id IS NOT NULL")


def downgrade() -> None:
    # Deliberately leave the additive mode column in place: dropping it would
    # erase the distinction needed to keep automatic routes non-sticky.
    pass
