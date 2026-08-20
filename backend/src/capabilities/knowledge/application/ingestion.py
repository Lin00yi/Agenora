"""Knowledge-ingestion use cases and HTTP-independent worker handoff."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def enqueue_documents(session: AsyncSession, document_ids: list[str]) -> list[Any]:
    """Durably enqueue documents before any in-process background handoff."""
    from src.storage.jobs.ingestion import enqueue_ingestion

    return [await enqueue_ingestion(session, document_id=document_id) for document_id in document_ids]


def handoff_ingestion(background: Any, jobs: list[Any]) -> None:
    """Schedule best-effort execution; the durable queue remains authoritative."""
    from src.storage.jobs.ingestion import run_ingestion_job

    for job in jobs:
        background.add_task(run_ingestion_job, job.id)
