"""Tests for the external, bounded user-memory maintenance sweep."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.conversations.models import Conversation, UserMemory


@pytest.mark.asyncio
async def test_maintenance_expires_and_backfills_memories(db, create_user, monkeypatch):
    from src.storage.vector import embedding
    from src.storage.jobs import memory as memory_maintenance
    from src.storage.database import get_session_factory

    user = await create_user("memory-worker@example.com")

    async def fake_embed_batch(texts, *, batch_size=32, cfg=None):  # noqa: ARG001
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(embedding, "embed_batch", fake_embed_batch)
    monkeypatch.setattr(embedding, "embedding_fingerprint", lambda cfg=None: "worker-space")
    monkeypatch.setattr(memory_maintenance, "resolve_user_embedding", lambda _user: object())

    factory = get_session_factory()
    async with factory() as session:
        session.add_all(
            [
                UserMemory(
                    id=str(uuid.uuid4()), user_id=user.id, type="explicit",
                    content="团队使用 TypeScript。", status="active",
                ),
                UserMemory(
                    id=str(uuid.uuid4()), user_id=user.id, type="explicit",
                    content="已过期的自动记忆", status="active",
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                ),
            ]
        )
        await session.commit()

        result = await memory_maintenance.run_memory_maintenance(
            session, user_limit=10, embedding_limit_per_user=10
        )
        rows = list(
            (
                await session.execute(select(UserMemory).where(UserMemory.user_id == user.id))
            ).scalars()
        )

    assert result.users_scanned == 1
    assert result.expired == 1
    assert result.embeddings_backfilled == 1
    assert sum(row.status == "expired" for row in rows) == 1
    active = next(row for row in rows if row.status == "active")
    assert active.embedding_fingerprint == "worker-space"
    assert active.embedding_json == "[1.0,0.0]"


@pytest.mark.asyncio
async def test_maintenance_finalizes_idle_conversations(db, create_user, monkeypatch):
    from src.storage.jobs import memory as memory_maintenance
    from src.storage.database import get_session_factory

    user = await create_user("idle-memory-worker@example.com")
    conv_id = str(uuid.uuid4())
    old_time = datetime.now(timezone.utc) - timedelta(hours=25)

    async def fake_extract(*args, **kwargs):  # noqa: ANN002, ANN003
        return {"messages_scanned": 2, "rule_candidates": 0, "llm_candidates": 1, "stored": 1}

    monkeypatch.setattr(memory_maintenance, "extract_conversation_memories", fake_extract)
    monkeypatch.setattr(memory_maintenance, "resolve_user_embedding", lambda _user: None)
    monkeypatch.setattr(memory_maintenance, "resolve_user_llm", lambda _user: None)
    monkeypatch.setattr(memory_maintenance, "resolve_system_llm", lambda: None)

    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Conversation(
                id=conv_id,
                user_id=user.id,
                title="idle",
                created_at=old_time,
                updated_at=old_time,
            )
        )
        await session.commit()

        result = await memory_maintenance.run_memory_maintenance(
            session,
            user_limit=10,
            embedding_limit_per_user=0,
            idle_hours=24,
            idle_limit_per_user=10,
        )
        conv = (await session.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one()

    assert result.idle_conversations_scanned == 1
    assert result.idle_conversations_finalized == 1
    assert result.idle_memories_extracted == 1
    assert conv.finalized_at is not None
