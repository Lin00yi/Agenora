"""Durable document-ingest queue backed by the application database."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.database import get_session_factory, init_db
from src.capabilities.knowledge.domain.models import Document, IngestionJob

log = structlog.get_logger()

_LEASE_SECONDS = 60 * 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def enqueue_ingestion(
    session: AsyncSession,
    *,
    document_id: str,
    max_attempts: int = 3,
) -> IngestionJob:
    """Create one durable job unless the document already has active work."""
    active = (
        await session.execute(
            select(IngestionJob)
            .where(
                IngestionJob.document_id == document_id,
                IngestionJob.status.in_(("pending", "running")),
            )
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        return active
    job = IngestionJob(
        id=str(uuid.uuid4()),
        document_id=document_id,
        max_attempts=max(1, min(int(max_attempts), 10)),
    )
    session.add(job)
    await session.flush()
    return job


async def _claim_job(job_id: str) -> tuple[str, str] | None:
    """Atomically lease a pending or abandoned job across all app workers."""
    factory = get_session_factory()
    now = _utcnow()
    stale_before = now - timedelta(seconds=_LEASE_SECONDS)
    token = str(uuid.uuid4())
    async with factory() as session:
        result = await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .where(
                or_(
                    (IngestionJob.status == "pending")
                    & (IngestionJob.available_at <= now),
                    (IngestionJob.status == "running")
                    & (IngestionJob.claimed_at.is_not(None))
                    & (IngestionJob.claimed_at < stale_before),
                )
            )
            .values(
                status="running",
                attempts=IngestionJob.attempts + 1,
                claimed_at=now,
                claim_token=token,
                error="",
            )
        )
        if not result.rowcount:
            await session.rollback()
            return None
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        await session.commit()
        return job.document_id, token


async def run_ingestion_job(job_id: str) -> bool:
    """Claim, execute and finalize one job. Returns True only when claimed."""
    claimed = await _claim_job(job_id)
    if claimed is None:
        return False
    document_id, token = claimed

    try:
        # The ingest function records document-level failure details.  Resolve
        # credentials from the persisted KB/user rows rather than serializing a
        # plaintext credential into this durable queue.
        from src.capabilities.knowledge.application.ingestion import ingest_document

        await ingest_document(document_id)
    except Exception as exc:  # noqa: BLE001 - finalization below schedules retry
        run_error = str(exc)[:2000]
        log.exception("ingestion_job_execution_failed", job_id=job_id, error=run_error)
    else:
        run_error = ""

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None or job.claim_token != token:
            return True
        doc = await session.get(Document, document_id)
        now = _utcnow()
        if doc is not None and doc.status == "done":
            job.status = "done"
            job.completed_at = now
            job.error = ""
        else:
            reason = run_error or (doc.error if doc is not None else "document was deleted")
            job.error = (reason or "ingest did not complete")[:2000]
            if job.attempts >= job.max_attempts or doc is None:
                job.status = "failed"
                job.completed_at = now
            else:
                job.status = "pending"
                # Bounded exponential retry: 5s, 10s, 20s ...; a worker CLI
                # or the next API handoff may claim it once this time arrives.
                job.available_at = now + timedelta(seconds=5 * (2 ** (job.attempts - 1)))
                job.claim_token = None
                job.claimed_at = None
        await session.commit()
        log.info("ingestion_job_finalized", job_id=job_id, status=job.status, attempts=job.attempts)
    return True


async def recover_ingestion_jobs(*, limit: int = 100) -> int:
    """Run one bounded recovery sweep; safe to call in each worker process."""
    factory = get_session_factory()
    now = _utcnow()
    stale_before = now - timedelta(seconds=_LEASE_SECONDS)
    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(IngestionJob.id)
                    .where(
                        or_(
                            (IngestionJob.status == "pending")
                            & (IngestionJob.available_at <= now),
                            (IngestionJob.status == "running")
                            & (IngestionJob.claimed_at.is_not(None))
                            & (IngestionJob.claimed_at < stale_before),
                        )
                    )
                    .order_by(IngestionJob.available_at, IngestionJob.created_at)
                    .limit(max(1, min(limit, 1_000)))
                )
            ).scalars()
        )
    claimed = 0
    for job_id in rows:
        claimed += int(await run_ingestion_job(job_id))
    return claimed


async def worker_main(*, poll_seconds: float = 2.0) -> None:
    await init_db()
    while True:
        count = await recover_ingestion_jobs()
        if not count:
            await asyncio.sleep(max(0.2, poll_seconds))


if __name__ == "__main__":
    asyncio.run(worker_main())
