"""Baseline marker for deployments predating Alembic-managed schema creation."""

from typing import Sequence, Union

revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = "0000_schema_bootstrap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intentionally empty: local disposable schemas use bootstrap initialization.
    pass


def downgrade() -> None:
    pass
