"""Knowledge-domain SQLAlchemy models.

Each KB owns a vector collection named `kb_{kb.id}` and any number of Document
rows describing the upload sources. Vectors live in the configured vector backend, not
SQL — these tables are just metadata + ingest bookkeeping.

Schema decisions:
- `KB.user_id` is a soft FK (string UUID) — we don't add ON DELETE CASCADE
  because we never expose a "delete user" path, and accidentally deleting all
  of a user's KBs via SQL would be very expensive (vector collections leak).
  Use the explicit DELETE /api/kbs/{id} route which handles both sides.
- `KB.embedding_model` records the model used at create-time so a future model
  swap doesn't silently corrupt search (we re-create the collection then).
- `Document.status` is a string enum maintained at the application layer; we
  don't use SQL ENUM to keep migrations painless on SQLite.
- `KB.is_system` (M4) marks built-in read-only KBs that all users can read
  but only the seeder can write. No system KB is shipped by default.
- `KBMember` (v2-M9) carries collaboration state:
    established (kb_id, user_id) → role. Rows cascade-delete with the parent KB.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


DocStatus = Literal["pending", "ingesting", "done", "failed"]
SourceType = Literal["file", "url"]
Role = Literal["owner", "editor", "viewer"]
MemberRole = Literal["editor", "viewer"]
ChunkStrategy = Literal[
    "recursive",
    "markdown_heading",
    "semantic",
    "table_aware",
    "code",
    "parent_child",
]

# Sentinel user_id reserved for built-in system KBs, if any are added later.
# Real users get random uuid4 ids.
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"


class KB(Base):
    """Knowledge Base — top-level container."""

    __tablename__ = "kbs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="")

    # Embedding lineage: which model produced the vectors. Vector dim is implied.
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    vector_size: Mapped[int] = mapped_column(Integer, default=0)

    # Denormalized count maintained by ingest pipeline (Σ over docs.chunks_count).
    chunks_count: Mapped[int] = mapped_column(Integer, default=0)

    # Built-in / read-only flag for optional system KBs. No system KB is seeded.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # v3-M3: owner-controlled toggle for Milvus grouping_search.
    # When True, KBSearchTool passes group_by_field="doc_id" so each document
    # contributes at most one chunk to top-k results. Helps when one long
    # document otherwise dominates retrieval. Only affects user KBs.
    grouping_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Knowledge-graph recall via LightRAG Server (opt-in). When True, ingest
    # also pushes parsed_text to LightRAG and chat runs search_kg in parallel
    # with search_kb (dense + BM25).
    kg_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )

    # v3-M7: per-KB embedding override (independent from user-level cfg).
    # When set, this KB's documents were ingested with these credentials and
    # KBSearchTool re-embeds queries with the same model. NULL on all four =
    # fall back to the user-level resolve_user_embedding().
    embedding_provider:       Mapped[Optional[str]] = mapped_column(String(32),  nullable=True, default=None)
    embedding_base_url:       Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    embedding_api_key_enc:    Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, default=None)
    embedding_model_override: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)

    # v3-M7: per-KB reranker override (opt-in, default off). reranker_enabled
    # MUST be True AND the four config cols populated for KBSearchTool to
    # consult the configured /rerank endpoint. NULL on all = fall back to
    # user-level resolve_user_reranker() (which may also be off → no rerank).
    # System KBs strictly skip reranker (handled in KBSearchTool).
    reranker_provider:    Mapped[Optional[str]] = mapped_column(String(32),  nullable=True, default=None)
    reranker_base_url:    Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    reranker_api_key_enc: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, default=None)
    reranker_model:       Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    reranker_enabled:     Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )

    # v4: per-KB chunking defaults (chars). Document-level overrides win when set.
    chunk_strategy: Mapped[str] = mapped_column(
        String(32), default="recursive", nullable=False
    )
    chunk_target: Mapped[int] = mapped_column(Integer, default=1500, nullable=False)
    chunk_max_size: Mapped[int] = mapped_column(Integer, default=1800, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=150, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="kb",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    members: Mapped[list["KBMember"]] = relationship(
        back_populates="kb",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    eval_config: Mapped[Optional["KbEvalConfig"]] = relationship(
        back_populates="kb",
        cascade="all, delete-orphan",
        uselist=False,
    )

    eval_runs: Mapped[list["KbEvalRun"]] = relationship(
        back_populates="kb",
        cascade="all, delete-orphan",
    )

    @property
    def collection_name(self) -> str:
        """Vector collection name for this KB (`kb_{uuid without dashes}`)."""
        return f"kb_{self.id.replace('-', '')}"

    async def role_for(
        self, session: AsyncSession, user_id: str
    ) -> Optional[Role]:
        """Return the highest role this user has for this KB, or None.

        Precedence: owner > editor > viewer > None.
        System KBs return 'viewer' for everyone (read-only, no member rows).

        v2-M9: replaces the old `user_id == owner OR is_system` two-state
        check. Used by `kb/routes.py` helpers and `api/chat/routes.py`.
        """
        if self.user_id == user_id:
            return "owner"
        if self.is_system:
            return "viewer"
        m = (
            await session.execute(
                select(KBMember).where(
                    KBMember.kb_id == self.id, KBMember.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        return m.role if m else None  # type: ignore[return-value]

    def to_public_dict(self, my_role: Optional[Role] = None) -> dict:
        docs = self.documents or []
        status_counts = {
            "pending": 0,
            "ingesting": 0,
            "done": 0,
            "failed": 0,
        }
        for doc in docs:
            if doc.status in status_counts:
                status_counts[doc.status] += 1
        out = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "embedding_model": self.embedding_model,
            "vector_size": self.vector_size,
            "chunks_count": self.chunks_count,
            "documents_count": len(docs),
            "document_status_counts": status_counts,
            "is_system": bool(self.is_system),
            "grouping_enabled": bool(self.grouping_enabled),
            "kg_enabled": bool(getattr(self, "kg_enabled", False)),
            "chunk_strategy": self.chunk_strategy or "recursive",
            "chunk_target": self.chunk_target,
            "chunk_max_size": self.chunk_max_size,
            "chunk_overlap": self.chunk_overlap,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if my_role is not None:
            out["my_role"] = my_role
        return out


class Document(Base):
    """One uploaded file / URL within a KB."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kbs.id", ondelete="CASCADE"), index=True, nullable=False
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    # "file" or "url" — drives parser selection in ingest.py
    source_type: Mapped[str] = mapped_column(String(16), default="file")
    source_url: Mapped[str] = mapped_column(String(2048), default="")

    # Lifecycle: pending → ingesting → done | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    chunks_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")

    # v4: parsed full text (post-extraction) + optional chunk-param overrides.
    parsed_text: Mapped[str] = mapped_column(Text, default="")
    chunk_strategy: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, default=None
    )
    chunk_target: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    chunk_max_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    chunk_overlap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)

    # v4: when False, all chunks from this document are excluded from KB search.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # LightRAG Server sync bookkeeping (independent of vector ingest status).
    # pending|processing|done|failed|skipped
    kg_status: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    kg_track_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    kg_doc_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    kg_error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    kb: Mapped[KB] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Chunk.chunk_idx",
    )

    def to_public_dict(
        self,
        *,
        include_parsed_text: bool = False,
        kb: "KB | None" = None,
    ) -> dict:
        effective_strategy = self.chunk_strategy or (kb.chunk_strategy if kb else None)
        effective_target = self.chunk_target or (kb.chunk_target if kb else None)
        effective_max_size = self.chunk_max_size or (kb.chunk_max_size if kb else None)
        effective_overlap = self.chunk_overlap if self.chunk_overlap is not None else (
            kb.chunk_overlap if kb else None
        )
        out = {
            "id": self.id,
            "kb_id": self.kb_id,
            "filename": self.filename,
            "mime": self.mime,
            "size_bytes": self.size_bytes,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "status": self.status,
            "chunks_count": self.chunks_count,
            "error": self.error or None,
            "chunk_strategy": self.chunk_strategy,
            "chunk_target": self.chunk_target,
            "chunk_max_size": self.chunk_max_size,
            "chunk_overlap": self.chunk_overlap,
            "effective_chunk_strategy": effective_strategy,
            "effective_chunk_target": effective_target,
            "effective_chunk_max_size": effective_max_size,
            "effective_chunk_overlap": effective_overlap,
            "parsed_text_length": len(self.parsed_text or ""),
            "enabled": bool(self.enabled),
            "kg_status": self.kg_status or None,
            "kg_error": self.kg_error or None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_parsed_text:
            out["parsed_text"] = self.parsed_text or ""
        return out


class IngestionJob(Base):
    """Durable, retryable work item for one document ingest.

    FastAPI BackgroundTasks are only a low-latency handoff: a separate worker
    claims this row, so process restarts and multiple web workers cannot lose
    or double-run the authoritative task.
    """

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class Chunk(Base):
    """One text chunk within a document — source of truth for chunk management.

    Vectors in Qdrant/Milvus mirror this row; search reads payload.text but
    management UI/API reads/writes here first, then re-syncs the vector store.
    """

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kb_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    chunk_idx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "kb_id": self.kb_id,
            "chunk_idx": self.chunk_idx,
            "text": self.text,
            "char_count": self.char_count,
            "enabled": bool(self.enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KBMember(Base):
    """Established (kb_id, user_id) → role mapping. v2-M9.

    Composite PK (kb_id, user_id) gives natural uniqueness — a user can only
    have one role per KB. Owner is NOT in this table (owner = kbs.user_id);
    members are strictly editor / viewer.

    user_id is soft FK (same convention as kbs.user_id) — we don't cascade on
    user deletion since we don't expose a delete-user path. kb_id cascades so
    member rows go away when the KB is deleted.
    """

    __tablename__ = "kb_members"

    kb_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("kbs.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "editor" | "viewer"
    invited_by: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    kb: Mapped[KB] = relationship(back_populates="members")

    def to_public_dict(self) -> dict:
        return {
            "kb_id": self.kb_id,
            "user_id": self.user_id,
            "role": self.role,
            "invited_by": self.invited_by or None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KbEvalConfig(Base):
    """Per-KB golden set + quality gate for retrieval regression."""

    __tablename__ = "kb_eval_configs"

    kb_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("kbs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    golden_set_jsonl: Mapped[str] = mapped_column(Text, nullable=False, default="")
    gate_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    golden_set_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    kb: Mapped[KB] = relationship(back_populates="eval_config")


class KbEvalRun(Base):
    """One retrieval-regression or offline-replay evaluation against a KB."""

    __tablename__ = "kb_eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kb_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("kbs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    run_type: Mapped[str] = mapped_column(String(16), nullable=False)  # regression | replay
    golden_set_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    k: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    report_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retrieval_jsonl_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    kb: Mapped[KB] = relationship(back_populates="eval_runs")

    def to_public_dict(self, *, include_report: bool = False) -> dict:
        report: dict = {}
        if self.report_json:
            try:
                parsed = json.loads(self.report_json)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                report = parsed
        metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        out = {
            "id": self.id,
            "kb_id": self.kb_id,
            "run_type": self.run_type,
            "golden_set_hash": self.golden_set_hash,
            "k": self.k,
            "gate_passed": bool(self.gate_passed),
            "metrics": metrics,
            "case_count": report.get("case_count"),
            "missing_count": len(report.get("missing_prediction_ids") or []),
            "created_by": self.created_by or None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_report:
            out["report"] = report
            out["retrieval_jsonl_path"] = self.retrieval_jsonl_path or None
        return out
