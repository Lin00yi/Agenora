from __future__ import annotations

import uuid

import pytest


def _bearer(user):
    from src.auth.tokens import issue_token

    return {"Authorization": f"Bearer {issue_token(user.id, user.email)}"}


@pytest.mark.asyncio
async def test_deleting_referenced_profile_requires_and_applies_replacement(client, create_user):
    from sqlalchemy import select

    from src.conversations.models import Conversation
    from src.infra.crypto import encrypt
    from src.storage.database import get_session_factory
    from src.capabilities.settings.domain.models import LLMConnection, LLMModelProfile

    user = await create_user("profile-delete@example.com")
    connection_id = str(uuid.uuid4())
    old_profile_id = str(uuid.uuid4())
    replacement_profile_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            LLMConnection(
                id=connection_id,
                user_id=user.id,
                display_name="Test connection",
                provider="openai-compat",
                base_url="https://example.test/v1",
                api_key_enc=encrypt("test-key"),
            )
        )
        session.add_all(
            [
                LLMModelProfile(
                    id=old_profile_id,
                    user_id=user.id,
                    connection_id=connection_id,
                    display_name="Old model",
                    model_id="old-model",
                ),
                LLMModelProfile(
                    id=replacement_profile_id,
                    user_id=user.id,
                    connection_id=connection_id,
                    display_name="Replacement model",
                    model_id="replacement-model",
                ),
                Conversation(
                    id=conversation_id,
                    user_id=user.id,
                    title="Historical conversation",
                    llm_profile_id=old_profile_id,
                    llm_model="old-model",
                ),
            ]
        )
        await session.commit()

    blocked = await client.request(
        "DELETE", f"/api/settings/llm/models/{old_profile_id}", headers=_bearer(user)
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == {
        "code": "model_profile_in_use",
        "conversation_count": 1,
        "message": "该模型仍被 1 个历史会话使用，请选择替代模型后再移除。",
    }

    deleted = await client.request(
        "DELETE",
        f"/api/settings/llm/models/{old_profile_id}",
        headers=_bearer(user),
        json={"replacement_profile_id": replacement_profile_id},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"migrated_conversations": 1}

    async with factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        old_profile = await session.get(LLMModelProfile, old_profile_id)
        replacement = await session.scalar(
            select(LLMModelProfile).where(LLMModelProfile.id == replacement_profile_id)
        )
    assert conversation is not None
    assert conversation.llm_profile_id == replacement_profile_id
    assert conversation.llm_model == "replacement-model"
    assert old_profile is None
    assert replacement is not None
