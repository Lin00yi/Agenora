"""Conversation-scoped durable LangGraph checkpoint storage.

SQLite is retained solely as the zero-dependency local-development backend.
PostgreSQL deployments must use the shared saver so an interrupt can resume on
any API replica rather than only on the process that created it.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.settings import get_settings


CheckpointBackend = Literal["sqlite", "postgres"]


def resolve_checkpoint_backend(settings: Any | None = None) -> CheckpointBackend:
    """Choose a topology-safe saver from the configured application database."""
    settings = settings or get_settings()
    requested = str(getattr(settings, "agent_checkpoint_backend", "auto") or "auto").strip().lower()
    if requested == "postgres":
        return "postgres"
    if requested == "sqlite":
        return "sqlite"
    database_url = str(getattr(settings, "database_url", "") or "")
    return "postgres" if database_url.startswith("postgresql") else "sqlite"


def checkpoint_postgres_url(settings: Any | None = None) -> str:
    """Return a psycopg-compatible URL without leaking SQLAlchemy driver names."""
    settings = settings or get_settings()
    configured = str(getattr(settings, "agent_checkpoint_database_url", "") or "").strip()
    source = configured or str(getattr(settings, "database_url", "") or "")
    if source.startswith("postgresql+asyncpg://"):
        return "postgresql://" + source.removeprefix("postgresql+asyncpg://")
    if source.startswith("postgresql+psycopg://"):
        return "postgresql://" + source.removeprefix("postgresql+psycopg://")
    if source.startswith("postgres://"):
        return "postgresql://" + source.removeprefix("postgres://")
    return source


@asynccontextmanager
async def open_agent_checkpointer() -> AsyncIterator[Any]:
    """Open an async durable saver for one chat graph invocation.

    Checkpoints are keyed by the stable conversation thread ID, so a later
    HTTP request can resume the interrupted graph. PostgreSQL saver setup is
    idempotent and is deliberately performed before serving an invocation;
    production migrations own application tables, while LangGraph owns its
    isolated checkpoint tables.
    """
    if resolve_checkpoint_backend() == "postgres":
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:  # pragma: no cover - exercised in production image
            raise RuntimeError(
                "PostgreSQL checkpoint backend requires langgraph-checkpoint-postgres. "
                "Install backend with the [postgres] extra."
            ) from exc
        url = checkpoint_postgres_url()
        if not url.startswith("postgresql://"):
            raise RuntimeError("AGENT_CHECKPOINT_DATABASE_URL must be a PostgreSQL URL")
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            yield saver
        return

    path = Path(get_settings().agent_checkpoint_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        await saver.conn.execute("PRAGMA journal_mode=WAL")
        await saver.conn.execute("PRAGMA busy_timeout=15000")
        yield saver


def checkpoint_config(*, user_id: str | None, conversation_id: str) -> dict:
    """Namespace the workflow by user and conversation, never by model input."""
    return {"configurable": {"thread_id": f"chat:{user_id or 'anonymous'}:{conversation_id}"}}
