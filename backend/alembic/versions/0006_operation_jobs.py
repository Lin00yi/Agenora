"""Create the shared durable operation control plane."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_operation_jobs"
down_revision: Union[str, Sequence[str], None] = "0005_shared_runtime_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "operation_jobs" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "operation_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operation_jobs_kind", "operation_jobs", ["kind"])
    op.create_index("ix_operation_jobs_status", "operation_jobs", ["status"])
    op.create_index("ix_operation_jobs_idempotency_key", "operation_jobs", ["idempotency_key"])
    op.create_index("ix_operation_jobs_available_at", "operation_jobs", ["available_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "operation_jobs" in sa.inspect(bind).get_table_names():
        for name in (
            "ix_operation_jobs_available_at",
            "ix_operation_jobs_idempotency_key",
            "ix_operation_jobs_status",
            "ix_operation_jobs_kind",
        ):
            op.drop_index(name, table_name="operation_jobs")
        op.drop_table("operation_jobs")
