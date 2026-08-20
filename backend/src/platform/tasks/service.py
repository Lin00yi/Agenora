"""Lease-based task queue and built-in operation handlers.

The database is the authoritative queue. FastAPI BackgroundTasks may invoke a
job immediately as an optimisation, but a worker will always recover it after
a process crash. No task payload contains decrypted credentials.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.persistence.database import get_session_factory

from .models import OperationJob

log = structlog.get_logger()
_LEASE_SECONDS = 30 * 60
_MAX_ERROR_LENGTH = 2_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _payload(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _read_payload(job: OperationJob) -> dict[str, Any]:
    try:
        value = json.loads(job.payload_json or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


async def enqueue_operation(
    session: AsyncSession,
    *,
    kind: str,
    payload: dict[str, Any] | None,
    idempotency_key: str,
    max_attempts: int = 3,
) -> OperationJob:
    """Persist one operation, returning an already-active equivalent if present."""
    normalized_kind = kind.strip().lower()
    key = idempotency_key.strip()
    if not normalized_kind or not key:
        raise ValueError("operation kind and idempotency_key are required")
    # PostgreSQL advisory locks serialize the lookup + insert below across API
    # and worker replicas. SQLite remains a local-development fallback.
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(
            hashlib.blake2b(
                f"{normalized_kind}:{key}".encode("utf-8"), digest_size=8
            ).digest(),
            byteorder="big",
            signed=True,
        )
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    existing = (
        await session.execute(
            select(OperationJob)
            .where(
                OperationJob.kind == normalized_kind,
                OperationJob.idempotency_key == key,
                OperationJob.status.in_(("pending", "running")),
            )
            .order_by(OperationJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    job = OperationJob(
        id=str(uuid.uuid4()),
        kind=normalized_kind,
        payload_json=_payload(payload),
        idempotency_key=key[:200],
        max_attempts=max(1, min(int(max_attempts), 10)),
    )
    session.add(job)
    await session.flush()
    return job


async def _claim(job_id: str) -> tuple[str, str] | None:
    """Atomically take a pending or abandoned operation across worker replicas."""
    now = _utcnow()
    token = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        claimed = await session.execute(
            update(OperationJob)
            .where(OperationJob.id == job_id)
            .where(
                or_(
                    and_(OperationJob.status == "pending", OperationJob.available_at <= now),
                    and_(
                        OperationJob.status == "running",
                        OperationJob.claimed_at.is_not(None),
                        OperationJob.claimed_at < now - timedelta(seconds=_LEASE_SECONDS),
                    ),
                )
            )
            .values(
                status="running",
                attempts=OperationJob.attempts + 1,
                claimed_at=now,
                claim_token=token,
                error="",
            )
        )
        if not claimed.rowcount:
            await session.rollback()
            return None
        await session.commit()
    return job_id, token


async def _execute(job: OperationJob) -> dict[str, Any]:
    """Dispatch the closed built-in catalog; unknown kinds fail into dead letter."""
    payload = _read_payload(job)
    if job.kind == "ingest_document":
        from src.capabilities.knowledge.application.ingestion import ingest_document

        await ingest_document(str(payload["document_id"]))
        return {"document_id": str(payload["document_id"])}
    if job.kind == "sync_lightrag_document":
        from src.capabilities.knowledge.graph.sync import sync_document_to_lightrag

        await sync_document_to_lightrag(str(payload["document_id"]))
        return {"document_id": str(payload["document_id"])}
    if job.kind == "memory_maintenance":
        from src.capabilities.memory.application.worker import run_memory_maintenance

        factory = get_session_factory()
        async with factory() as session:
            result = await run_memory_maintenance(
                session,
                user_limit=int(payload.get("user_limit") or 200),
                embedding_limit_per_user=int(payload.get("embedding_limit_per_user") or 100),
            )
        return result.to_dict()
    if job.kind == "memory_heavy":
        from src.capabilities.identity.models import User
        from src.capabilities.memory.application.lifecycle import finalize_memory_rows_heavy

        user_id = str(payload["user_id"])
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return {"skipped": "user_deleted"}
            from src.capabilities.settings.domain.models import resolve_user_embedding

            result = await finalize_memory_rows_heavy(
                session,
                user_id=user_id,
                memory_ids=[str(item) for item in payload.get("memory_ids") or []],
                embedding_cfg=resolve_user_embedding(user),
            )
            await session.commit()
        return result
    if job.kind == "kb_regression":
        from src.capabilities.knowledge.application.evaluation import run_regression
        from src.capabilities.knowledge.domain.models import KB

        factory = get_session_factory()
        async with factory() as session:
            kb = await session.get(KB, str(payload["kb_id"]))
            if kb is None:
                return {"skipped": "kb_deleted"}
            run = await run_regression(session, kb, created_by=str(payload["created_by"]))
        return {"kb_id": kb.id, "eval_run_id": run.id, "gate_passed": run.gate_passed}
    if job.kind == "kb_rebuild":
        from src.capabilities.knowledge.application.rebuild import rebuild_knowledge_base

        return await rebuild_knowledge_base(str(payload["kb_id"]))
    if job.kind == "retention_sweep":
        from src.platform.retention import run_retention_sweep

        factory = get_session_factory()
        async with factory() as session:
            result = await run_retention_sweep(
                session, limit=int(payload.get("limit") or 200)
            )
        return result.to_dict()
    raise ValueError(f"unknown operation kind: {job.kind}")


async def run_operation_job(job_id: str) -> bool:
    """Claim, run and finalize a durable job; safe for an immediate handoff or worker."""
    claimed = await _claim(job_id)
    if claimed is None:
        return False
    _, token = claimed
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(OperationJob, job_id)
        if job is None:
            return True
        try:
            result = await _execute(job)
            error = ""
        except Exception as exc:  # noqa: BLE001 - finalization controls retry/dead letter
            result = {}
            error = str(exc)[:_MAX_ERROR_LENGTH]
            log.exception("operation_failed", job_id=job_id, kind=job.kind, error=error)

    async with factory() as session:
        job = await session.get(OperationJob, job_id)
        if job is None or job.claim_token != token:
            return True
        now = _utcnow()
        if not error:
            job.status = "done"
            job.completed_at = now
            job.result_json = _payload(result)
            job.error = ""
        elif job.attempts >= job.max_attempts:
            job.status = "dead_letter"
            job.completed_at = now
            job.error = error
        else:
            job.status = "pending"
            job.available_at = now + timedelta(seconds=5 * (2 ** (job.attempts - 1)))
            job.claimed_at = None
            job.claim_token = None
            job.error = error
        await session.commit()
        log.info("operation_finalized", job_id=job.id, kind=job.kind, status=job.status)
    return True


async def recover_operations(*, limit: int = 100) -> int:
    """Claim a bounded ready batch; each row has its own durable lease."""
    now = _utcnow()
    factory = get_session_factory()
    async with factory() as session:
        job_ids = list(
            (
                await session.execute(
                    select(OperationJob.id)
                    .where(
                        or_(
                            and_(OperationJob.status == "pending", OperationJob.available_at <= now),
                            and_(
                                OperationJob.status == "running",
                                OperationJob.claimed_at.is_not(None),
                                OperationJob.claimed_at < now - timedelta(seconds=_LEASE_SECONDS),
                            ),
                        )
                    )
                    .order_by(OperationJob.available_at, OperationJob.created_at)
                    .limit(max(1, min(limit, 1_000)))
                )
            ).scalars()
        )
    results = await asyncio.gather(*(run_operation_job(job_id) for job_id in job_ids))
    return sum(1 for item in results if item)


async def migrate_legacy_ingestion_jobs(*, limit: int = 200) -> int:
    """Move unfinished pre-control-plane ingestion rows without losing work.

    The old table is intentionally retained for one release so an upgraded
    deployment can drain it safely. Each old row becomes a new operation with
    a stable migration key, then is marked ``migrated`` only after the new row
    is durable.
    """
    from src.capabilities.knowledge.domain.models import IngestionJob

    factory = get_session_factory()
    async with factory() as session:
        legacy_rows = list(
            (
                await session.execute(
                    select(IngestionJob)
                    .where(IngestionJob.status.in_(("pending", "running")))
                    .order_by(IngestionJob.created_at)
                    .limit(max(1, min(limit, 1_000)))
                )
            ).scalars()
        )
        for legacy in legacy_rows:
            await enqueue_operation(
                session,
                kind="ingest_document",
                payload={"document_id": legacy.document_id},
                idempotency_key=f"legacy-ingest:{legacy.id}",
                max_attempts=legacy.max_attempts or 3,
            )
            legacy.status = "migrated"
        await session.commit()
    return len(legacy_rows)
