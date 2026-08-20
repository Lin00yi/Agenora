"""Prevent duplicate active operation jobs across database replicas."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_operation_job_idempotency"
down_revision: Union[str, Sequence[str], None] = "0006_operation_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "operation_jobs" not in sa.inspect(bind).get_table_names():
        return
    op.create_index(
        "uq_operation_jobs_active_key",
        "operation_jobs",
        ["kind", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
        sqlite_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "operation_jobs" in sa.inspect(bind).get_table_names():
        op.drop_index("uq_operation_jobs_active_key", table_name="operation_jobs")
