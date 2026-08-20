"""Single durable worker for ingestion, memory, graph sync and evaluation jobs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from src.bootstrap.database import initialize_database
from src.platform.persistence.database import get_session_factory
from src.platform.tasks.service import enqueue_operation, migrate_legacy_ingestion_jobs, recover_operations

log = structlog.get_logger()


def _hour_slot(now: datetime) -> str:
    return now.strftime("%Y%m%d%H")


def _day_slot(now: datetime) -> str:
    return now.strftime("%Y%m%d")


async def _enqueue_periodic_operations() -> None:
    """Schedule bounded maintenance once per UTC hour without a separate cron."""
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        await enqueue_operation(
            session,
            kind="memory_maintenance",
            payload={"user_limit": 200, "embedding_limit_per_user": 100},
            idempotency_key=f"hourly:{_hour_slot(now)}",
            max_attempts=3,
        )
        await enqueue_operation(
            session,
            kind="retention_sweep",
            payload={"limit": 200},
            idempotency_key=f"daily:{_day_slot(now)}",
            max_attempts=3,
        )
        await session.commit()


async def worker_main(*, poll_seconds: float = 2.0) -> None:
    await initialize_database()
    while True:
        try:
            await migrate_legacy_ingestion_jobs()
            await _enqueue_periodic_operations()
            count = await recover_operations()
            if not count:
                await asyncio.sleep(max(0.2, poll_seconds))
        except Exception as exc:  # noqa: BLE001 - worker must self-heal
            log.exception("operation_worker_failed", error=str(exc))
            await asyncio.sleep(max(1.0, poll_seconds))


if __name__ == "__main__":
    asyncio.run(worker_main())
