"""Create PostgreSQL-shared runtime state tables.

Rate-limit events deliberately live outside SQLAlchemy product models: they
are high-churn operational state with a small, explicit schema and retention
window. LangGraph checkpoint tables are created by its PostgreSQL saver under
its own versioned schema contract.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_shared_runtime_state"
down_revision: Union[str, Sequence[str], None] = "0004_conversation_kb_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "rate_limit_hits" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "rate_limit_hits",
        sa.Column("rate_key", sa.String(length=160), nullable=False),
        sa.Column("ts", sa.Float(), nullable=False),
    )
    op.create_index("ix_rate_limit_hits_key_ts", "rate_limit_hits", ["rate_key", "ts"])


def downgrade() -> None:
    bind = op.get_bind()
    if "rate_limit_hits" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_rate_limit_hits_key_ts", table_name="rate_limit_hits")
        op.drop_table("rate_limit_hits")
