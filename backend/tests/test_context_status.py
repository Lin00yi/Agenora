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


@pytest.mark.asyncio
async def test_context_status_uses_system_context_window_for_auto_model(
    db,
    create_user,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.conversations.models import Conversation
    from src.conversations import routes
    from src.infra.database import get_session_factory
    from src.settings_user.models import UserLLMConfig

    user = await create_user("system-window@example.com")
    conversation = Conversation(id=str(uuid.uuid4()), user_id=user.id, title="auto")

    factory = get_session_factory()
    async with factory() as session:
        session.add(conversation)
        await session.commit()

        monkeypatch.setattr(routes, "resolve_user_llm", lambda _user: None)
        monkeypatch.setattr(
            routes,
            "resolve_system_llm",
            lambda: UserLLMConfig(
                provider="openai-compat",
                base_url="https://api.deepseek.com",
                api_key="test-key",
                default_model="deepseek-v4-flash",
                complex_model="deepseek-v4-pro",
                context_window=1_000_000,
            ),
        )

        status = await routes.get_conversation_context_status(conversation.id, user, session)

    assert status["context_window"] == 1_000_000
