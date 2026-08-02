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
