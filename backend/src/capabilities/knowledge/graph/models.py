"""Agenora-owned knowledge-graph records.

LightRAG and Neo4j remain optional execution infrastructure.  These models are
the product contract: they keep graph access scoped to a KB and make every
relationship traceable to a document version and an extraction run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.persistence.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GraphSource(Base):
    """A rescannable KB source.  Files are extractable but not remotely scanned."""

    __tablename__ = "graph_sources"
    __table_args__ = (UniqueConstraint("kb_id", "document_id", name="uq_graph_sources_document"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("kbs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="document")
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scan_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "enabled": bool(self.enabled),
            "scan_interval_minutes": self.scan_interval_minutes,
            "next_scan_at": self.next_scan_at.isoformat() if self.next_scan_at else None,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "last_error": self.last_error or None,
        }


class GraphScan(Base):
    """One manual, scheduled, or webhook-triggered graph refresh."""

    __tablename__ = "graph_scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("kbs.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("graph_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    source_revision: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    documents_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "trigger": self.trigger,
            "status": self.status,
            "documents_seen": self.documents_seen,
            "documents_changed": self.documents_changed,
            "documents_extracted": self.documents_extracted,
            "error": self.error or None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GraphExtractionRun(Base):
    """Versioned extraction audit record for one document."""

    __tablename__ = "graph_extraction_runs"
    __table_args__ = (UniqueConstraint("document_id", "content_hash", name="uq_graph_extract_document_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("kbs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    scan_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("graph_scans.id", ondelete="SET NULL"), nullable=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor: Mapped[str] = mapped_column(String(32), nullable=False, default="llm")
    extractor_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    entities_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GraphEntity(Base):
    __tablename__ = "graph_entities"
    __table_args__ = (UniqueConstraint("kb_id", "normalized_name", "entity_type", name="uq_graph_entity_identity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("kbs.id", ondelete="CASCADE"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, default="concept")
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_public_dict(self) -> dict:
        try:
            aliases = json.loads(self.aliases_json or "[]")
        except (TypeError, ValueError):
            aliases = []
        return {
            "id": self.id,
            "name": self.canonical_name,
            "type": self.entity_type,
            "aliases": aliases if isinstance(aliases, list) else [],
            "summary": self.summary or None,
            "confidence": round(float(self.confidence or 0), 3),
            "evidence_count": self.evidence_count,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }


class GraphRelation(Base):
    __tablename__ = "graph_relations"
    __table_args__ = (UniqueConstraint("kb_id", "fingerprint", name="uq_graph_relation_fingerprint"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("kbs.id", ondelete="CASCADE"), index=True)
    source_entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_entities.id", ondelete="CASCADE"), index=True)
    target_entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_entities.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source_entity_id,
            "target": self.target_entity_id,
            "type": self.relation_type,
            "confidence": round(float(self.confidence or 0), 3),
            "evidence_count": self.evidence_count,
        }


class GraphEvidence(Base):
    __tablename__ = "graph_evidence"
    __table_args__ = (UniqueConstraint("relation_id", "document_id", "content_hash", "quote", name="uq_graph_evidence_identity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("kbs.id", ondelete="CASCADE"), index=True)
    relation_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_relations.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    extraction_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("graph_extraction_runs.id", ondelete="CASCADE"), index=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "quote": self.quote,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
