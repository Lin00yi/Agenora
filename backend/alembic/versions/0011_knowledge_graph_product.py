"""Add Agenora-owned graph source, scan, relation, and evidence records."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_knowledge_graph_product"
down_revision: Union[str, Sequence[str], None] = "0010_memory_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "graph_sources" not in tables:
        op.create_table(
            "graph_sources",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kb_id", sa.String(36), sa.ForeignKey("kbs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE")),
            sa.Column("source_type", sa.String(16), nullable=False, server_default="document"),
            sa.Column("source_url", sa.String(2048), nullable=False, server_default=""),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("scan_interval_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_scan_at", sa.DateTime(timezone=True)),
            sa.Column("last_scan_at", sa.DateTime(timezone=True)),
            sa.Column("last_content_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("kb_id", "document_id", name="uq_graph_sources_document"),
        )
        op.create_index("ix_graph_sources_kb_id", "graph_sources", ["kb_id"])
        op.create_index("ix_graph_sources_document_id", "graph_sources", ["document_id"])
        op.create_index("ix_graph_sources_next_scan_at", "graph_sources", ["next_scan_at"])
    if "graph_scans" not in tables:
        op.create_table(
            "graph_scans",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kb_id", sa.String(36), sa.ForeignKey("kbs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_id", sa.String(36), sa.ForeignKey("graph_sources.id", ondelete="SET NULL")),
            sa.Column("trigger", sa.String(16), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("source_revision", sa.String(128), nullable=False, server_default=""),
            sa.Column("documents_seen", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("documents_changed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("documents_extracted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("kb_id", "source_id", "status"):
            op.create_index(f"ix_graph_scans_{column}", "graph_scans", [column])
    if "graph_extraction_runs" not in tables:
        op.create_table(
            "graph_extraction_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kb_id", sa.String(36), sa.ForeignKey("kbs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("scan_id", sa.String(36), sa.ForeignKey("graph_scans.id", ondelete="SET NULL")),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("extractor", sa.String(32), nullable=False, server_default="llm"),
            sa.Column("extractor_model", sa.String(128), nullable=False, server_default=""),
            sa.Column("extractor_version", sa.String(32), nullable=False, server_default="v1"),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("entities_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("relations_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("document_id", "content_hash", name="uq_graph_extract_document_hash"),
        )
        for column in ("kb_id", "document_id", "scan_id", "status"):
            op.create_index(f"ix_graph_extraction_runs_{column}", "graph_extraction_runs", [column])
    if "graph_entities" not in tables:
        op.create_table(
            "graph_entities",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kb_id", sa.String(36), sa.ForeignKey("kbs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canonical_name", sa.String(255), nullable=False),
            sa.Column("normalized_name", sa.String(255), nullable=False),
            sa.Column("entity_type", sa.String(64), nullable=False, server_default="concept"),
            sa.Column("aliases_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("kb_id", "normalized_name", "entity_type", name="uq_graph_entity_identity"),
        )
        op.create_index("ix_graph_entities_kb_id", "graph_entities", ["kb_id"])
        op.create_index("ix_graph_entities_status", "graph_entities", ["status"])
    if "graph_relations" not in tables:
        op.create_table(
            "graph_relations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kb_id", sa.String(36), sa.ForeignKey("kbs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_entity_id", sa.String(36), sa.ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_entity_id", sa.String(36), sa.ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False),
            sa.Column("relation_type", sa.String(64), nullable=False),
            sa.Column("fingerprint", sa.String(128), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("kb_id", "fingerprint", name="uq_graph_relation_fingerprint"),
        )
        for column in ("kb_id", "source_entity_id", "target_entity_id", "status"):
            op.create_index(f"ix_graph_relations_{column}", "graph_relations", [column])
    if "graph_evidence" not in tables:
        op.create_table(
            "graph_evidence",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kb_id", sa.String(36), sa.ForeignKey("kbs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("relation_id", sa.String(36), sa.ForeignKey("graph_relations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chunk_id", sa.String(36), sa.ForeignKey("chunks.id", ondelete="SET NULL")),
            sa.Column("extraction_run_id", sa.String(36), sa.ForeignKey("graph_extraction_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("quote", sa.Text(), nullable=False, server_default=""),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("relation_id", "document_id", "content_hash", "quote", name="uq_graph_evidence_identity"),
        )
        for column in ("kb_id", "relation_id", "document_id", "extraction_run_id", "active"):
            op.create_index(f"ix_graph_evidence_{column}", "graph_evidence", [column])


def downgrade() -> None:
    # Graph evidence is user-owned derived data. Forward-only migration avoids
    # silently discarding audit history during an application rollback.
    pass
