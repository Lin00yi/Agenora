"""Standalone maintenance worker for long-term user memory.

Run this module from one external scheduler/worker process, never once per web
worker. It intentionally shares the same deterministic consolidation and
embedding code used by the conversation write path.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.conversations.context import (
    backfill_user_memory_embeddings,
    consolidate_user_memories,
)
from src.infra.database import get_session_factory, init_db
from src.settings_user import resolve_user_embedding

log = structlog.get_logger()


@dataclass
class MemoryMaintenanceResult:
    users_scanned: int = 0
    expired: int = 0
    superseded: int = 0
    deduplicated: int = 0
    embeddings_backfilled: int = 0
    failed_users: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


async def run_memory_maintenance(
    session: AsyncSession,
    *,
    user_limit: int = 200,
    embedding_limit_per_user: int = 100,
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


async def main() -> None:
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        result = await run_memory_maintenance(session)
    print(result.to_dict())  # noqa: T201 - CLI result for Cron logs


if __name__ == "__main__":
    asyncio.run(main())
