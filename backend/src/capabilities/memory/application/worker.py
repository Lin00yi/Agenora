"""Standalone maintenance worker for long-term user memory.

Run this module from one external scheduler/worker process, never once per web
worker. It intentionally shares the same deterministic consolidation and
embedding code used by the conversation write path.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.capabilities.identity.models import User
from src.harness.context import (
    backfill_user_memory_embeddings,
    consolidate_user_memories,
    extract_conversation_memories,
)
from src.capabilities.conversations.models import Conversation
from src.bootstrap.database import initialize_database
from src.platform.persistence.database import get_session_factory
from src.capabilities.settings.domain.models import resolve_system_llm, resolve_user_embedding, resolve_user_llm

log = structlog.get_logger()


@dataclass
class MemoryMaintenanceResult:
    users_scanned: int = 0
    expired: int = 0
    superseded: int = 0
    deduplicated: int = 0
    embeddings_backfilled: int = 0
    idle_conversations_scanned: int = 0
    idle_conversations_finalized: int = 0
    idle_memories_extracted: int = 0
    failed_users: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


async def run_memory_maintenance(
    session: AsyncSession,
    *,
    user_limit: int = 200,
    embedding_limit_per_user: int = 100,
    idle_hours: int = 24,
    idle_limit_per_user: int = 20,
) -> MemoryMaintenanceResult:
    """Run one bounded, idempotent sweep and commit after each user.

    The external scheduler must ensure only one invocation is active across a
    deployment. Per-user commits keep a transient provider failure from rolling
    back cleanup work already completed for other users.
    """
    result = MemoryMaintenanceResult()
    users = list(
        (
            await session.execute(select(User).order_by(User.id).limit(user_limit))
        ).scalars()
    )
    for user in users:
        result.users_scanned += 1
        try:
            idle_stats = await extract_idle_conversation_memories(
                session,
                user=user,
                idle_hours=idle_hours,
                limit=idle_limit_per_user,
            )
            result.idle_conversations_scanned += idle_stats["scanned"]
            result.idle_conversations_finalized += idle_stats["finalized"]
            result.idle_memories_extracted += idle_stats["stored"]
            stats = await consolidate_user_memories(session, user_id=user.id)
            result.expired += stats["expired"]
            result.superseded += stats["superseded"]
            result.deduplicated += stats["deduplicated"]
            result.embeddings_backfilled += await backfill_user_memory_embeddings(
                session,
                user_id=user.id,
                embedding_cfg=resolve_user_embedding(user),
                limit=embedding_limit_per_user,
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - continue with other users
            await session.rollback()
            result.failed_users += 1
            log.warning("memory_maintenance_user_failed", user_id=user.id, error=str(exc))
    log.info("memory_maintenance_completed", **result.to_dict())
    return result


async def extract_idle_conversation_memories(
    session: AsyncSession,
    *,
    user: User,
    idle_hours: int = 24,
    limit: int = 20,
) -> dict[str, int]:
    if idle_hours <= 0 or limit <= 0:
        return {"scanned": 0, "finalized": 0, "stored": 0}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=idle_hours)
    rows = list(
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.user_id == user.id,
                    Conversation.finalized_at.is_(None),
                    Conversation.updated_at <= cutoff,
                )
                .order_by(Conversation.updated_at)
                .limit(limit)
            )
        ).scalars()
    )
    finalized = 0
    stored = 0
    llm_cfg = resolve_user_llm(user) or resolve_system_llm()
    embedding_cfg = resolve_user_embedding(user)
    for conv in rows:
        claimed = await session.execute(
            update(Conversation)
            .where(
                Conversation.id == conv.id,
                Conversation.user_id == user.id,
                Conversation.finalized_at.is_(None),
            )
            .values(finalized_at=now, updated_at=now)
        )
        if not claimed.rowcount:
            continue
        memory = await extract_conversation_memories(
            session,
            conversation_id=conv.id,
            user_id=user.id,
            kb_id=conv.kb_id,
            llm_cfg=llm_cfg,
            embedding_cfg=embedding_cfg,
        )
        finalized += 1
        stored += memory["stored"]
    return {"scanned": len(rows), "finalized": finalized, "stored": stored}


async def main() -> None:
    await initialize_database()
    factory = get_session_factory()
    async with factory() as session:
        result = await run_memory_maintenance(session)
    print(result.to_dict())  # noqa: T201 - CLI result for Cron logs


if __name__ == "__main__":
    asyncio.run(main())
