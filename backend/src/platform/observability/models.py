"""Persisted internal traces (Langfuse-like span trees)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.platform.persistence.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ttft_ms(started_at: datetime | None, metadata: dict) -> int | None:
    """Return generation time-to-first-token from the stored completion start.

    Langfuse calls this ``completion_start_time``.  Keeping the derived value
    in the admin response (rather than duplicating it in the database) makes
    existing traces readable as soon as the UI gains TTFT support.
    """
    value = metadata.get("completion_start_time")
    if started_at is None or not isinstance(value, str) or not value:
        return None
    try:
        completion_started_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if completion_started_at.tzinfo is None:
        completion_started_at = completion_started_at.replace(tzinfo=timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return max(0, int((completion_started_at - started_at).total_seconds() * 1000))


class Trace(Base):
    """One end-to-end request / chat turn."""

    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="chat")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")

    input_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    observations: Mapped[list["Observation"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="Observation.started_at",
        lazy="selectin",
    )

    def metadata_dict(self) -> dict:
        if not self.metadata_json:
            return {}
        try:
            parsed = json.loads(self.metadata_json)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def to_summary_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "name": self.name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "total_cost_usd": self.total_cost_usd,
            "metadata": self.metadata_dict(),
            "observation_count": len(self.observations) if self.observations is not None else 0,
        }


class Observation(Base):
    """One span / generation / tool node in a trace tree."""

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("traces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    parent_observation_id: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="span")
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    input_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    trace: Mapped[Trace] = relationship(back_populates="observations")

    def usage_dict(self) -> dict | None:
        if not self.usage_json:
            return None
        try:
            parsed = json.loads(self.usage_json)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def metadata_dict(self) -> dict:
        if not self.metadata_json:
            return {}
        try:
            parsed = json.loads(self.metadata_json)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def to_dict(self) -> dict:
        # Import here to keep ORM model import lightweight and avoid a runtime
        # dependency from trace persistence on the admin-facing catalog.
        from src.platform.observability.catalog import observation_lifecycle

        metadata = self.metadata_dict()
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_observation_id": self.parent_observation_id,
            "type": self.type,
            "name": self.name,
            "lifecycle": observation_lifecycle(self.name),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "model": self.model,
            "usage": self.usage_dict(),
            "cost_usd": self.cost_usd,
            "input_preview": self.input_preview,
            "output_preview": self.output_preview,
            "metadata": metadata,
            # TTFT is meaningful for generation nodes only. Historical rows
            # without completion_start_time deliberately remain null.
            "ttft_ms": _ttft_ms(self.started_at, metadata) if self.type == "generation" else None,
        }
