"""Regression coverage for the context-status endpoint's legacy DB fallback."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_context_status_remains_available_without_summary_table(db, create_user):
    """A pre-summary database must not make the composer show an error state."""
    from src.context import compute_budget
    from src.conversations.models import Conversation, Message
    from src.api.routes.conversations import _build_context_status
    from src.storage.database import get_engine, get_session_factory

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
    assert status["recent_message_count"] == 1


def test_completed_response_trace_is_synchronized_to_current_history() -> None:
    from src.api.routes.conversations import _synchronize_memory_trace_after_completion

    trace = {
        "recent_message_count": 1,
        "prompt": {
            "context_window": 1_000_000,
            "tokens": {
                "system": 837,
                "tools": 742,
                "history": 11,
                "summary": 0,
                "rag": 0,
                "total_input": 1_590,
            },
        },
    }
    synced = _synchronize_memory_trace_after_completion(
        trace,
        {"current_tokens": 68, "context_window": 1_000_000, "recent_message_count": 2},
    )

    assert synced is not None
    assert synced["recent_message_count"] == 2
    assert synced["prompt"]["tokens"]["history"] == 68
    assert synced["prompt"]["tokens"]["total_input"] == 1_647


def test_completed_response_trace_does_not_double_count_summary() -> None:
    from src.api.routes.conversations import _synchronize_memory_trace_after_completion

    trace = {
        "prompt": {"tokens": {"history": 10, "summary": 30, "total_input": 100}}
    }
    synced = _synchronize_memory_trace_after_completion(
        trace,
        {"current_tokens": 50, "context_window": 16_000, "recent_message_count": 4},
    )

    assert synced is not None
    assert synced["prompt"]["tokens"]["history"] == 20
    assert synced["prompt"]["tokens"]["total_input"] == 110


@pytest.mark.asyncio
async def test_context_status_uses_system_context_window_for_auto_model(
    db,
    create_user,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.conversations.models import Conversation
    from src.api.routes import conversations as routes
    from src.storage.database import get_session_factory
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


@pytest.mark.asyncio
async def test_model_selection_patch_returns_status_for_the_target_window(
    db,
    create_user,
    monkeypatch: pytest.MonkeyPatch,
):
    """The composer can refresh before the next message is sent."""
    from src.api.routes import conversations as routes
    from src.conversations.models import Conversation, Message
    from src.storage.database import get_session_factory
    from src.settings_user.models import UserLLMConfig

    user = await create_user("model-switch-status@example.com")
    conversation = Conversation(id=str(uuid.uuid4()), user_id=user.id, title="switch")
    message = Message(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        role="user",
        content="上下文切换预检",
    )
    cfg = UserLLMConfig(
        provider="openai-compat",
        base_url="https://example.invalid/v1",
        api_key="test-key",
        default_model="local-small",
        complex_model="local-small",
        context_window=4_096,
    )

    async def target_cfg(*_args, **_kwargs):
        return cfg

    monkeypatch.setattr(routes, "_context_cfg_for_conversation", target_cfg)
    factory = get_session_factory()
    async with factory() as session:
        session.add_all((conversation, message))
        await session.commit()
        payload = await routes.patch_conversation(
            conversation.id,
            routes.PatchConversationRequest(llm_model="local-small"),
            user,
            session,
        )

    assert payload["llm_model"] == "local-small"
    assert payload["context_status"]["context_window"] == 4_096
    assert payload["context_status"]["available_tokens"] < 4_096
