"""Knowledge-ingestion use cases and HTTP-independent worker handoff."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from src.platform.files.object_storage import get_object_storage
from src.platform.vector import get_vector_store
from src.capabilities.knowledge.application.chunks import (
    chunk_document_text,
    clear_document_chunks,
    persist_ingested_chunks,
)
from src.capabilities.knowledge.domain.models import Document, KB
from src.platform.files.parsers import dispatch, parse_url
from src.platform.persistence.database import get_session_factory

from .documents import upload_key

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserEmbeddingConfig

log = structlog.get_logger()

async def enqueue_documents(session: AsyncSession, document_ids: list[str]) -> list[Any]:
    """Durably enqueue documents before any in-process background handoff."""
    from src.capabilities.knowledge.application.jobs import enqueue_ingestion

    return [await enqueue_ingestion(session, document_id=document_id) for document_id in document_ids]


def handoff_ingestion(background: Any, jobs: list[Any]) -> None:
    """Schedule best-effort execution; the durable queue remains authoritative."""
    from src.capabilities.knowledge.application.jobs import run_ingestion_job

    for job in jobs:
        background.add_task(run_ingestion_job, job.id)


async def ingest_document(
    doc_id: str,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
) -> None:
    """Parse, chunk and persist one uploaded document outside the HTTP request.

    Every database transaction is intentionally short: remote parsing and
    vector embedding occur after the claim transaction has committed, which
    prevents a slow provider from holding the relational write lock.
    """
    factory = get_session_factory()
    async with factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            log.warning("ingest_no_such_doc", doc_id=doc_id)
            return
        kb = await session.get(KB, doc.kb_id)
        if kb is None:
            doc.status = "failed"
            doc.error = "parent KB no longer exists"
            await session.commit()
            return
        kb_snapshot = {
            "id": kb.id,
            "collection_name": kb.collection_name,
        }
        if embedding_cfg is None:
            from src.capabilities.identity.models import User
            from src.capabilities.knowledge.application.configuration import resolve_kb_embedding

            owner = await session.get(User, kb.user_id)
            embedding_cfg = resolve_kb_embedding(kb, owner)
        doc_snapshot = {
            "kb_id": doc.kb_id,
            "filename": doc.filename,
            "source_type": doc.source_type,
            "source_url": doc.source_url or "",
        }
        previous_chunks = doc.chunks_count or 0
        doc.status = "ingesting"
        await session.commit()

    new_status, new_chunks, error_msg = "failed", 0, ""
    try:
        if doc_snapshot["source_type"] == "url":
            _, text = await parse_url(doc_snapshot["source_url"])
        else:
            content = await get_object_storage().get(
                upload_key(doc_snapshot["kb_id"], doc_id, doc_snapshot["filename"])
            )
            _, text = dispatch(doc_snapshot["filename"], content)
        if not text.strip():
            raise ValueError("empty content after parsing")

        async with factory() as session:
            kb_row = await session.get(KB, kb_snapshot["id"])
            doc_row = await session.get(Document, doc_id)
            if kb_row is None or doc_row is None:
                raise ValueError("document or kb disappeared during ingest")
            doc_row.parsed_text = text
            await session.commit()
            chunks = chunk_document_text(kb_row, doc_row, text)
        if not chunks:
            raise ValueError("chunker produced 0 chunks")

        store = get_vector_store()
        if not hasattr(store, "create_collection"):
            raise RuntimeError("KB ingest requires a multi-collection backend (qdrant or milvus)")
        async with factory() as session:
            kb_row = await session.get(KB, kb_snapshot["id"])
            doc_row = await session.get(Document, doc_id)
            if kb_row is None or doc_row is None:
                raise ValueError("document or kb disappeared during ingest")
            new_chunks = await persist_ingested_chunks(
                session, store, kb_row, doc_row, chunks, embedding_cfg
            )
            doc_row.chunks_count = new_chunks
            await session.commit()
        new_status = "done"
        log.info("ingest_done", doc_id=doc_id, kb_id=kb_snapshot["id"], chunks=new_chunks, collection=kb_snapshot["collection_name"])
    except Exception as exc:  # noqa: BLE001 - record the document failure for the durable queue
        error_msg = str(exc)[:2000]
        log.exception("ingest_failed", doc_id=doc_id, error=error_msg)

    kg_enabled = False
    async with factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            return
        doc.status = new_status
        doc.chunks_count = new_chunks if new_status == "done" else 0
        doc.error = error_msg
        if new_status == "done":
            kb = await session.get(KB, doc.kb_id)
            if kb is not None:
                kb.chunks_count = (kb.chunks_count or 0) - previous_chunks + new_chunks
                kg_enabled = bool(getattr(kb, "kg_enabled", False))
        await session.commit()

    if new_status == "done" and kg_enabled:
        try:
            from src.capabilities.knowledge.graph.sync import sync_document_to_lightrag

            await sync_document_to_lightrag(doc_id)
        except Exception as exc:  # noqa: BLE001 - vector ingest already succeeded
            log.warning("lightrag_sync_invoke_failed", doc_id=doc_id, error=str(exc)[:500])


async def delete_document_chunks(collection_name: str, doc_id: str) -> None:
    """Drop a document's vector and relational chunks; safe to call repeatedly."""
    store = get_vector_store()
    factory = get_session_factory()
    async with factory() as session:
        await clear_document_chunks(session, store, collection_name, doc_id)
        await session.commit()
