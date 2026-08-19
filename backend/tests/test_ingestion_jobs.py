"""Regression coverage for the durable document ingestion queue."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest


async def _make_document(create_user, create_kb):
    from src.storage.database import get_session_factory
    from src.kb.models import Document

    user = await create_user("ingest-jobs@example.test")
    kb = await create_kb(user.id, "Queued KB")
    doc = Document(id=str(uuid.uuid4()), kb_id=kb.id, filename="queued.md")
    factory = get_session_factory()
    async with factory() as session:
        session.add(doc)
        await session.commit()
    return doc


@pytest.mark.asyncio
async def test_ingestion_job_marks_done_after_worker_completes(db, create_user, create_kb, monkeypatch):
    from src.storage.database import get_session_factory
    from src.storage.jobs.ingestion import enqueue_ingestion, run_ingestion_job
    from src.kb.models import Document, IngestionJob
    import src.kb.ingest as ingest

    doc = await _make_document(create_user, create_kb)
    factory = get_session_factory()
    async with factory() as session:
        job = await enqueue_ingestion(session, document_id=doc.id)
        await session.commit()

    async def complete(document_id: str) -> None:
        async with factory() as session:
            row = await session.get(Document, document_id)
            assert row is not None
            row.status = "done"
            await session.commit()

    monkeypatch.setattr(ingest, "ingest_document", complete)
    assert await run_ingestion_job(job.id) is True

    async with factory() as session:
        stored = await session.get(IngestionJob, job.id)
        assert stored is not None
        assert stored.status == "done"
        assert stored.attempts == 1
        assert stored.completed_at is not None


@pytest.mark.asyncio
async def test_ingestion_job_retries_then_records_terminal_failure(
    db, create_user, create_kb, monkeypatch
):
    from src.storage.database import get_session_factory
    from src.storage.jobs.ingestion import enqueue_ingestion, run_ingestion_job
    from src.kb.models import Document, IngestionJob
    import src.kb.ingest as ingest

    doc = await _make_document(create_user, create_kb)
    factory = get_session_factory()
    async with factory() as session:
        job = await enqueue_ingestion(session, document_id=doc.id, max_attempts=2)
        await session.commit()

    async def fail(document_id: str) -> None:
        async with factory() as session:
            row = await session.get(Document, document_id)
            assert row is not None
            row.status = "failed"
            row.error = "provider temporarily unavailable"
            await session.commit()

    monkeypatch.setattr(ingest, "ingest_document", fail)
    assert await run_ingestion_job(job.id) is True

    async with factory() as session:
        retrying = await session.get(IngestionJob, job.id)
        assert retrying is not None
        assert retrying.status == "pending"
        assert retrying.attempts == 1
        retrying.available_at = retrying.available_at - timedelta(minutes=1)
        await session.commit()

    assert await run_ingestion_job(job.id) is True
    async with factory() as session:
        failed = await session.get(IngestionJob, job.id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.attempts == 2
        assert failed.error == "provider temporarily unavailable"
