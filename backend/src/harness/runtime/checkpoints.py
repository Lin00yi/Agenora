"""Conversation-scoped durable LangGraph checkpoint storage."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.settings import get_settings


@asynccontextmanager
async def open_agent_checkpointer() -> AsyncIterator[AsyncSqliteSaver]:
    """Open an async, durable saver for one chat graph invocation.

    ``AsyncSqliteSaver`` is required because the supervisor uses ``ainvoke``.
    Checkpoints are still keyed by the stable conversation thread ID, so a
    later HTTP request can resume the interrupted graph from the same file.
    """
    path = Path(get_settings().agent_checkpoint_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        await saver.conn.execute("PRAGMA journal_mode=WAL")
        await saver.conn.execute("PRAGMA busy_timeout=15000")
        yield saver


def checkpoint_config(*, user_id: str | None, conversation_id: str) -> dict:
    """Namespace the workflow by user and conversation, never by model input."""
    return {"configurable": {"thread_id": f"chat:{user_id or 'anonymous'}:{conversation_id}"}}
