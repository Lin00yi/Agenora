"""Add per-KB golden-set eval config and run history.

The running application still calls ``Base.metadata.create_all()`` for legacy
personal deployments.  The conditional DDL therefore also supports databases
where a rolling application startup already created these tables before the
operator executes ``alembic upgrade head``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_kb_eval"
down_revision: Union[str, Sequence[str], None] = "0002_ingestion_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "kb_eval_configs" not in tables:
        op.create_table(
            "kb_eval_configs",
            sa.Column("kb_id", sa.String(length=36), nullable=False),
            sa.Column("golden_set_jsonl", sa.Text(), nullable=False, server_default=""),
            sa.Column("gate_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("golden_set_hash", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["kb_id"], ["kbs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("kb_id"),
        )

    if "kb_eval_runs" not in tables:
        op.create_table(
            "kb_eval_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("kb_id", sa.String(length=36), nullable=False),
            sa.Column("run_type", sa.String(length=16), nullable=False),
            sa.Column("golden_set_hash", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("k", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("report_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("gate_passed", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("retrieval_jsonl_path", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(length=36), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["kb_id"], ["kbs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_kb_eval_runs_kb_id", "kb_eval_runs", ["kb_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "kb_eval_runs" in tables:
        op.drop_index("ix_kb_eval_runs_kb_id", table_name="kb_eval_runs")
        op.drop_table("kb_eval_runs")
    if "kb_eval_configs" in tables:
        op.drop_table("kb_eval_configs")
