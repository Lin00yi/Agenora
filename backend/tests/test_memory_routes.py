from __future__ import annotations

import uuid

import pytest


def _bearer(user):
    from src.auth.tokens import issue_token

    return {"Authorization": f"Bearer {issue_token(user.id, user.email)}"}


@pytest.mark.asyncio
async def test_memory_list_status_filter_defaults_to_active(client, create_user):
    from src.conversations.models import UserMemory
    from src.infra.database import get_session_factory

    user = await create_user("memory-routes@example.com")
    factory = get_session_factory()
    async with factory() as session:
        session.add_all(
            [
                UserMemory(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    type="explicit",
                    content="Prefer concise answers.",
                    status="active",
                ),
                UserMemory(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    type="preference",
                    content="Old preference.",
                    status="superseded",
                ),
            ]
        )
        await session.commit()

    default_resp = await client.get("/api/conversations/memories", headers=_bearer(user))
    assert default_resp.status_code == 200
    assert [item["status"] for item in default_resp.json()] == ["active"]

    all_resp = await client.get(
        "/api/conversations/memories?status=all", headers=_bearer(user)
    )
    assert all_resp.status_code == 200
    assert {item["status"] for item in all_resp.json()} == {"active", "superseded"}


@pytest.mark.asyncio
async def test_finalize_conversation_runs_memory_extraction_once(
    client, create_user, monkeypatch
):
    from sqlalchemy import select

    from src.conversations.models import Conversation, Message
    from src.conversations import routes
    from src.infra.database import get_session_factory

    user = await create_user("finalize-memory@example.com")
    conv_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())

    async def fake_extract(*args, **kwargs):  # noqa: ANN002, ANN003
        return {"messages_scanned": 1, "rule_candidates": 0, "llm_candidates": 1, "stored": 1}

    monkeypatch.setattr(routes, "extract_conversation_memories", fake_extract)

    factory = get_session_factory()
    async with factory() as session:
        session.add(Conversation(id=conv_id, user_id=user.id, title="finalize"))
        session.add(
            Message(id=msg_id, conversation_id=conv_id, role="user", content="Remember me.")
        )
        await session.commit()

    first = await client.post(f"/api/conversations/{conv_id}/finalize", headers=_bearer(user))
    assert first.status_code == 200
    assert first.json()["already_finalized"] is False
    assert first.json()["memory"]["stored"] == 1
    assert first.json()["conversation"]["finalized_at"] is not None

    second = await client.post(f"/api/conversations/{conv_id}/finalize", headers=_bearer(user))
    assert second.status_code == 200
    assert second.json()["already_finalized"] is True
    assert second.json()["memory"]["stored"] == 0

    append = await client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=_bearer(user),
        json={"role": "user", "content": "Continue."},
    )
    assert append.status_code == 201
    async with factory() as session:
        conv = (
            await session.execute(select(Conversation).where(Conversation.id == conv_id))
        ).scalar_one()
    assert conv.finalized_at is None
