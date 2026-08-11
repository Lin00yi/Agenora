"""Baseline revision — existing DBs should ``alembic stamp head``.

Schema creation for greenfield / personal deploys still happens via
``init_db()`` (create_all + additive ALTER helpers). New forward-only changes
should be authored as subsequent Alembic revisions.
"""

from typing import Sequence, Union

revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intentionally empty: tables are created by init_db()/create_all today.
    pass


def downgrade() -> None:
    pass
