"""Retired travel demo KB is purged on startup and never re-seeded."""
from __future__ import annotations

import uuid

import pytest

from src.conversations.models import Conversation
from src.storage.database import get_session_factory
from src.kb.models import KB, SYSTEM_USER_ID
from src.kb.system_seed import LEGACY_TRAVEL_KB_ID, purge_legacy_travel_kb, seed_system_kbs


@pytest.mark.asyncio
async def test_purge_legacy_travel_kb_removes_row_and_unbinds_conversations(db, create_user):
    user = await create_user("owner@example.com")
    conv_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            KB(
                id=LEGACY_TRAVEL_KB_ID,
                user_id=SYSTEM_USER_ID,
                name="旅行演示库（可选）",
                description="retired",
                is_system=True,
            )
        )
        session.add(
            Conversation(
                id=conv_id,
                user_id=user.id,
                title="demo",
                kb_id=LEGACY_TRAVEL_KB_ID,
            )
        )
        await session.commit()

    await purge_legacy_travel_kb()

    async with factory() as session:
        assert await session.get(KB, LEGACY_TRAVEL_KB_ID) is None
        conv = await session.get(Conversation, conv_id)
        assert conv is not None
        assert conv.kb_id is None


@pytest.mark.asyncio
async def test_seed_system_kbs_does_not_recreate_travel_demo(db):
    await seed_system_kbs()
    factory = get_session_factory()
    async with factory() as session:
        assert await session.get(KB, LEGACY_TRAVEL_KB_ID) is None
