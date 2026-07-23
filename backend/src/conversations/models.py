"""Conversation, message, summary, and user memory SQLAlchemy models."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infra.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    """One chat thread owned by exactly one user."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), default="新对话", nullable=False)
    kb_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
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
            "title": self.title,
            "kb_id": self.kb_id,
            "llm_model": self.llm_model,
            "message_count": len(self.messages) if self.messages is not None else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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
        if self.tool_call_log:
            try:
                tools = json.loads(self.tool_call_log)
            except (ValueError, TypeError):
                tools = None

        return {
            "id": self.id,
            "role": self.role,
            "content": self.content or "",
            "tools": tools if tools is not None else ([] if self.role == "assistant" else None),
            "cost_usd": self.cost_usd,
            "error": self.error or None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


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
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
