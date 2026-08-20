"""Conversation, message, summary, and user memory SQLAlchemy models."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.platform.persistence.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime | None) -> str | None:
    """Serialize persisted timestamps as explicit UTC instants.

    SQLite does not retain timezone metadata for ``DateTime(timezone=True)``.
    The project stores these values in UTC, so values read back from SQLite can
    be naive even though they represent UTC.  Re-attaching UTC here keeps the
    API unambiguous and lets browsers render the user's local timezone.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class Conversation(Base):
    """One chat thread owned by exactly one user."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="新对话", nullable=False)
    kb_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    # Stable selection used by the multi-connection pool.  Keep llm_model for
    # old clients, imports, and a readable denormalised model identifier.
    llm_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="selectin",
    )

    def to_summary_dict(self) -> dict:
        return {
            "id": self.id,
            # SQLAlchemy applies column defaults on flush, but callers can
            # build a draft Conversation before it is persisted.  Keep the
            # public API stable for that normal in-memory path too.
            "title": self.title or "新对话",
            "kb_id": self.kb_id,
            "llm_model": self.llm_model,
            "llm_profile_id": self.llm_profile_id,
            "message_count": len(self.messages) if self.messages is not None else 0,
            "created_at": _isoformat_utc(self.created_at),
            "updated_at": _isoformat_utc(self.updated_at),
            "finalized_at": _isoformat_utc(self.finalized_at),
        }

    def to_dict_with_messages(self) -> dict:
        return {
            **self.to_summary_dict(),
            "messages": [m.to_public_dict() for m in self.messages] if self.messages else [],
        }


class Message(Base):
    """One user or assistant message in a conversation."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)

    tool_call_log: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    def to_public_dict(self) -> dict:
        tools: list | None = None
        parts: list | None = None
        memory_trace: dict | None = None
        citations: list | None = None
        if self.tool_call_log:
            try:
                parsed = json.loads(self.tool_call_log)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict) and (
                "tools" in parsed
                or "parts" in parsed
                or "memory_trace" in parsed
                or "citations" in parsed
            ):
                raw_tools = parsed.get("tools")
                tools = raw_tools if isinstance(raw_tools, list) else []
                raw_parts = parsed.get("parts")
                parts = raw_parts if isinstance(raw_parts, list) else None
                raw_trace = parsed.get("memory_trace")
                memory_trace = raw_trace if isinstance(raw_trace, dict) else None
                raw_citations = parsed.get("citations")
                citations = raw_citations if isinstance(raw_citations, list) else None
            elif isinstance(parsed, list):
                tools = parsed

        return {
            "id": self.id,
            "role": self.role,
            "content": self.content or "",
            "tools": tools if tools is not None else ([] if self.role == "assistant" else None),
            "parts": parts,
            "memory_trace": memory_trace,
            "citations": citations,
            "cost_usd": self.cost_usd,
            "error": self.error or None,
            "created_at": _isoformat_utc(self.created_at),
        }

    @staticmethod
    def encode_tool_call_log(
        tools: list | None,
        parts: list | None = None,
        memory_trace: dict | None = None,
        citations: list | None = None,
    ) -> str | None:
        """Serialize assistant timeline metadata into tool_call_log JSON.

        Legacy rows store a bare tools list. Newer rows that carry extras use
        a wrapped object so we avoid a schema migration while remaining
        backward-compatible on read. ``parts`` preserves the visible
        text/tool ordering for a streamed assistant turn.
        """
        tool_list = list(tools or [])
        part_list = list(parts or [])
        citation_list = list(citations or [])
        if part_list or memory_trace or citation_list:
            payload: dict = {"tools": tool_list}
            if part_list:
                payload["parts"] = part_list
            if memory_trace:
                payload["memory_trace"] = memory_trace
            if citation_list:
                payload["citations"] = citation_list
            return json.dumps(payload, ensure_ascii=False)
        if tool_list:
            return json.dumps(tool_list, ensure_ascii=False)
        return None


class ConversationSummary(Base):
    """Rolling compact summary for one long conversation."""

    __tablename__ = "conversation_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    covered_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    covered_message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Records the window that produced this compact view.  A later switch to a
    # larger model can safely rehydrate bounded raw detail without discarding
    # the durable rolling summary.
    source_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A background worker may precompute the first summary before the active
    # chat request reaches the compression threshold.  Prepared rows are not
    # injected until the threshold is crossed, so prewarming never shortens a
    # still-healthy conversation window.
    is_prepared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "summary": self.summary,
            "covered_message_id": self.covered_message_id,
            "covered_message_count": self.covered_message_count,
            "token_count": self.token_count,
            "source_model": self.source_model,
            "source_context_window": self.source_context_window,
            "is_prepared": self.is_prepared,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserMemory(Base):
    """Structured, user-scoped long-term memory across conversations."""

    __tablename__ = "user_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="personal", nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True, default=None)
    type: Mapped[str] = mapped_column(String(32), default="fact", nullable=False)
    memory_key: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True, default=None)
    memory_value: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_message_ids: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    source: Mapped[str] = mapped_column(String(32), default="explicit", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_memory_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    # Serialized normalized vector plus the embedding-space fingerprint. Text
    # keeps this feature portable across SQLite development and PostgreSQL;
    # the per-user memory volume is small, so no second vector database is
    # required for the initial hybrid-retrieval implementation.
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    embedding_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def to_public_dict(self) -> dict:
        source_ids: list[str] = []
        if self.source_message_ids:
            try:
                parsed = json.loads(self.source_message_ids)
                if isinstance(parsed, list):
                    source_ids = [str(x) for x in parsed]
            except (TypeError, ValueError):
                source_ids = []

        return {
            "id": self.id,
            "user_id": self.user_id,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "type": self.type,
            "key": self.memory_key,
            "value": self.memory_value,
            "content": self.content,
            "source_message_ids": source_ids,
            "source": self.source,
            "confidence": self.confidence,
            "importance": self.importance,
            "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "supersedes_memory_id": self.supersedes_memory_id,
            "has_embedding": bool(self.embedding_json and self.embedding_fingerprint),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
