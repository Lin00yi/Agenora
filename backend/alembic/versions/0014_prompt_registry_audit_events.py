"""Add append-only Prompt Registry audit events."""
import uuid
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014_prompt_registry_audit_events"
down_revision: Union[str, Sequence[str], None] = "0013_conversation_summary_prompt_trace"
branch_labels = None
depends_on = None


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"unsupported prompt version timestamp: {value!r}")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_exists = "prompt_template_audit_events" in inspector.get_table_names()
    if not table_exists:
        op.create_table(
            "prompt_template_audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "template_id",
                sa.String(36),
                sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(32), nullable=False),
            sa.Column("actor_admin_id", sa.String(36)),
            sa.Column("actor_email", sa.String(320)),
            sa.Column("source_version", sa.Integer()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_prompt_template_audit_events_template_id",
            "prompt_template_audit_events",
            ["template_id"],
        )
    # Versions created before this revision have no event rows.  Backfill only
    # facts that can be inferred from immutable version metadata; publish actor
    # identity was not stored before the audit table existed.
    versions = bind.execute(
        sa.text(
            "SELECT template_id, version, status, created_by_admin_id, created_at, published_at "
            "FROM prompt_template_versions"
        )
    ).mappings()
    existing = {
        (row["template_id"], int(row["version"]), row["action"])
        for row in bind.execute(
            sa.text("SELECT template_id, version, action FROM prompt_template_audit_events")
        ).mappings()
    }
    rows = []
    for version in versions:
        draft_key = (version["template_id"], int(version["version"]), "draft_saved")
        if draft_key not in existing:
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "template_id": version["template_id"],
                    "version": version["version"],
                    "action": "draft_saved",
                    "actor_admin_id": version["created_by_admin_id"],
                    "actor_email": None,
                    "source_version": None,
                    "created_at": _as_datetime(version["created_at"]),
                }
            )
        published_key = (version["template_id"], int(version["version"]), "published")
        if version["published_at"] is not None and published_key not in existing:
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "template_id": version["template_id"],
                    "version": version["version"],
                    "action": "published",
                    "actor_admin_id": None,
                    "actor_email": None,
                    "source_version": None,
                    "created_at": _as_datetime(version["published_at"] or version["created_at"]),
                }
            )
    if rows:
        op.bulk_insert(
            sa.table(
                "prompt_template_audit_events",
                sa.column("id", sa.String()),
                sa.column("template_id", sa.String()),
                sa.column("version", sa.Integer()),
                sa.column("action", sa.String()),
                sa.column("actor_admin_id", sa.String()),
                sa.column("actor_email", sa.String()),
                sa.column("source_version", sa.Integer()),
                sa.column("created_at", sa.DateTime(timezone=True)),
            ),
            rows,
        )


def downgrade() -> None:
    # Prompt audit records are append-only control-plane history.
    pass
