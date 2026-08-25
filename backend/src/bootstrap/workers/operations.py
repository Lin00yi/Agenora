"""Single durable worker for ingestion, memory, graph sync and evaluation jobs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from src.bootstrap.database import initialize_database
from src.platform.persistence.database import get_session_factory
from src.platform.tasks.models import OperationJob
from src.platform.tasks.service import enqueue_operation, migrate_legacy_ingestion_jobs, recover_operations
from src.settings import get_settings

log = structlog.get_logger()


def _hour_slot(now: datetime) -> str:
    return now.strftime("%Y%m%d%H")


def _day_slot(now: datetime) -> str:
    return now.strftime("%Y%m%d")


def worker_batch_limit() -> int:
    """Keep embedded Milvus Lite single-process and single-job in local dev.

    Milvus Lite is a file-backed embedded engine; concurrent operation jobs
    can contend for its client/database even when they share the API process.
    Network vector stores retain the normal bounded batch throughput.
    """
    settings = get_settings()
    uri = str(settings.milvus_uri or "").strip().lower()
    if str(settings.vector_store or "").strip().lower() == "milvus" and not uri.startswith(
        ("http://", "https://")
    ):
        return 1
    return 100


async def _enqueue_periodic_operations() -> None:
    """Schedule bounded maintenance once per UTC hour without a separate cron."""
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        periodic_operations = (
            (
                "memory_maintenance",
                {"user_limit": 200, "embedding_limit_per_user": 100},
                f"hourly:{_hour_slot(now)}",
            ),
            ("retention_sweep", {"limit": 200}, f"daily:{_day_slot(now)}"),
        )
        for kind, payload, idempotency_key in periodic_operations:
            # enqueue_operation intentionally permits a completed ordinary
            # operation to be submitted again. Periodic work is different:
            # its UTC slot must be represented by at most one durable job.
            existing = await session.scalar(
                select(OperationJob.id)
                .where(
                    OperationJob.kind == kind,
                    OperationJob.idempotency_key == idempotency_key,
                )
                .limit(1)
            )
            if existing is None:
                await enqueue_operation(
                    session,
                    kind=kind,
                    payload=payload,
                    idempotency_key=idempotency_key,
                    max_attempts=3,
                )
        await session.commit()
    # Graph scans are per-source schedules, not a global clock slot.  The
    # service advances each source before creating its durable scan operation.
    from src.capabilities.knowledge.graph.service import enqueue_due_graph_scans

    await enqueue_due_graph_scans(limit=50)


async def worker_main(*, poll_seconds: float = 2.0) -> None:
    await initialize_database()
    while True:
        try:
            await migrate_legacy_ingestion_jobs()
            await _enqueue_periodic_operations()
            count = await recover_operations(limit=worker_batch_limit())
            from src.capabilities.knowledge.graph.service import reconcile_graph_scans

            await reconcile_graph_scans()
            if not count:
                await asyncio.sleep(max(0.2, poll_seconds))
        except Exception as exc:  # noqa: BLE001 - worker must self-heal
            log.exception("operation_worker_failed", error=str(exc))
            await asyncio.sleep(max(1.0, poll_seconds))


if __name__ == "__main__":
    asyncio.run(worker_main())
