"""Destructive knowledge-base lifecycle use cases.

Authorization belongs to the HTTP boundary. This module owns the ordered
cleanup of relational metadata, vector data, graph copies, object storage and
derived evaluation artifacts.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.vector import get_vector_store
from src.capabilities.knowledge.domain.models import Document, IngestionJob, KB

from . import documents, evaluation


async def purge_kb(session: AsyncSession, kb: KB) -> None:
    """Permanently delete one KB and all of its derived data.

    Vector and graph copies are removed before the relational row so a failed
    cleanup can be retried with the source metadata still available.
    """
    collection_name, kb_id = kb.collection_name, kb.id
    docs = list((await session.execute(select(Document).where(Document.kb_id == kb_id))).scalars())

    if bool(getattr(kb, "kg_enabled", False)):
        from src.capabilities.knowledge.graph.sync import delete_document_from_lightrag

        for doc in docs:
            await delete_document_from_lightrag(
                kb_id=kb_id,
                kg_doc_id=getattr(doc, "kg_doc_id", "") or "",
                kg_track_id=getattr(doc, "kg_track_id", "") or "",
                strict=True,
            )

    await session.execute(delete(IngestionJob).where(IngestionJob.document_id.in_([doc.id for doc in docs])))
    store = get_vector_store()
    if hasattr(store, "delete_collection"):
        await store.delete_collection(collection_name)
    await session.delete(kb)
    await session.commit()
    await documents.delete_kb_uploads(kb_id)
    await evaluation.delete_run_files(kb_id)
