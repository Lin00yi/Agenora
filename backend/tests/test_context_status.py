"""Regression coverage for the context-status endpoint's legacy DB fallback."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_context_status_remains_available_without_summary_table(db, create_user):
    """A pre-summary database must not make the composer show an error state."""
    from src.conversations.context import compute_budget
    from src.conversations.models import Conversation, Message
    from src.conversations.routes import _build_context_status
    from src.infra.database import get_engine, get_session_factory

    user = await create_user("legacy-context-status@example.com")
    conversation = Conversation(id=str(uuid.uuid4()), user_id=user.id, title="旧会话")
    message = Message(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        role="user",
        content="保留上下文使用状态",
    )

    factory = get_session_factory()
    async with factory() as session:
        session.add_all((conversation, message))
        await session.commit()

    async with get_engine().begin() as connection:
        await connection.execute(text("DROP TABLE conversation_summaries"))

    async with factory() as session:
        status = await _build_context_status(session, conversation)

    assert status["state"] == "normal"
    assert status["summary"] is None
    assert status["current_tokens"] == compute_budget([message], None).current_history_tokens
