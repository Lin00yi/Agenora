"""Durable knowledge-base rebuild use case, independent from HTTP delivery."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.capabilities.identity.models import User
from src.capabilities.knowledge.application.configuration import resolve_kb_embedding
from src.capabilities.knowledge.application.ingestion import enqueue_documents
from src.capabilities.knowledge.application.vector_runtime import (
    get_vector_store,
    probe_vector_dimension,
)
from src.capabilities.knowledge.domain.models import Document, KB
from src.platform.persistence.database import get_session_factory


async def rebuild_knowledge_base(kb_id: str) -> dict[str, Any]:
    """Reset a collection and enqueue every current document for ingestion.

    The durable operation job is the caller. This function opens its own short
    transactions so a remote vector backend never holds a relational lock.
    """
    factory = get_session_factory()
    async with factory() as session:
        kb = await session.get(KB, kb_id)
        if kb is None:
            return {"skipped": "kb_deleted"}
        if kb.is_system:
            return {"skipped": "system_kb"}
        owner = await session.get(User, kb.user_id)
        embedding = resolve_kb_embedding(kb, owner)
        if embedding is None:
            raise ValueError("knowledge-base embedding is not configured")
        collection_name = kb.collection_name
        vector_size = kb.vector_size or await probe_vector_dimension(embedding)
        document_ids = list(
            (
                await session.execute(
                    select(Document.id)
                    .where(Document.kb_id == kb_id)
                    .order_by(Document.created_at)
                )
            ).scalars()
        )
        documents = list(
            (
                await session.execute(
                    select(Document).where(Document.id.in_(document_ids))
                )
            ).scalars()
        )
        for document in documents:
            document.status = "pending"
            document.chunks_count = 0
            document.error = ""
        kb.chunks_count = 0
        await session.commit()

    store = get_vector_store()
    if not hasattr(store, "delete_collection") or not hasattr(store, "create_collection"):
        raise ValueError("KB rebuild requires a multi-collection backend (qdrant or milvus)")
    await store.delete_collection(collection_name)
    await store.create_collection(collection_name, vector_size)

    async with factory() as session:
        # A KB can be deleted while its queued rebuild is waiting. Do not
        # resurrect document work after that explicit lifecycle operation.
        if await session.get(KB, kb_id) is None:
            return {"skipped": "kb_deleted"}
        jobs = await enqueue_documents(session, document_ids)
        await session.commit()
    return {
        "kb_id": kb_id,
        "collection": collection_name,
        "doc_count": len(document_ids),
        "ingestion_job_ids": [job.id for job in jobs],
    }
