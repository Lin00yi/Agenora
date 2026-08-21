"""Regression coverage for model-profile removal with conversation migration."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.capabilities.conversations.models import Conversation
from src.capabilities.identity.models import User
from src.capabilities.settings.application.model_profiles import delete_profile
from src.capabilities.settings.domain.models import LLMModelProfile
from src.platform.persistence.database import Base


@pytest.mark.asyncio
async def test_delete_profile_migrates_historical_conversations_to_replacement() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(id="user-1", email="user@example.com", password_hash="hash")
            previous = LLMModelProfile(
                id="profile-old",
                user_id=user.id,
                display_name="旧模型",
                model_id="old-model",
                enabled=True,
            )
            replacement = LLMModelProfile(
                id="profile-new",
                user_id=user.id,
                display_name="新模型",
                model_id="new-model",
                enabled=True,
            )
            conversation = Conversation(
                id="conversation-1",
                user_id=user.id,
                title="历史会话",
                llm_profile_id=previous.id,
                llm_model=previous.model_id,
            )
            session.add_all([user, previous, replacement, conversation])
            await session.commit()

            migrated = await delete_profile(
                session,
                profile_id=previous.id,
                user=user,
                replacement_id=replacement.id,
            )

            assert migrated == 1
            stored_conversation = await session.get(Conversation, conversation.id)
            assert stored_conversation is not None
            assert stored_conversation.llm_profile_id == replacement.id
            assert stored_conversation.llm_model == replacement.model_id
            old_profile = await session.scalar(
                select(LLMModelProfile).where(LLMModelProfile.id == previous.id)
            )
            assert old_profile is None
    finally:
        await engine.dispose()
