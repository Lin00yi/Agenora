"""Push / delete Agenora documents into LightRAG Server after vector ingest."""
from __future__ import annotations

import structlog

from src.storage.database import get_session_factory
from src.kb.models import Document, KB
from src.kg.lightrag_client import file_source_for_doc, get_lightrag_client
from src.settings import get_settings

log = structlog.get_logger()


async def sync_document_to_lightrag(doc_id: str) -> None:
    """Background: insert parsed_text into LightRAG when KB.kg_enabled."""
    settings = get_settings()
    client = get_lightrag_client()
    if not client.enabled or not settings.lightrag_enabled:
        return

    factory = get_session_factory()
    async with factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            return
        kb = await session.get(KB, doc.kb_id)
        if kb is None or not bool(getattr(kb, "kg_enabled", False)):
            doc.kg_status = "skipped"
            await session.commit()
            return
        if not (doc.parsed_text or "").strip():
            doc.kg_status = "failed"
            doc.kg_error = "empty parsed_text"
            await session.commit()
            return

        kb_id = kb.id
        text = doc.parsed_text
        filename = doc.filename
        file_source = file_source_for_doc(kb_id, doc.id, filename)
        doc.kg_status = "processing"
        doc.kg_error = ""
        await session.commit()

    try:
        result = await client.insert_text(
            kb_id=kb_id, text=text, file_source=file_source
        )
        track_id = ""
        if isinstance(result, dict):
            track_id = str(result.get("track_id") or "")
        lr_doc_ids = []
        if track_id:
            lr_doc_ids = await client.resolve_doc_ids_from_track(
                kb_id=kb_id, track_id=track_id
            )
        async with factory() as session:
            doc = await session.get(Document, doc_id)
            if doc is None:
                return
            doc.kg_track_id = track_id
            doc.kg_doc_id = lr_doc_ids[0] if lr_doc_ids else ""
            doc.kg_status = "done"
            doc.kg_error = ""
            await session.commit()
        log.info(
            "lightrag_sync_done",
            doc_id=doc_id,
            kb_id=kb_id,
            track_id=track_id,
            kg_doc_id=lr_doc_ids[0] if lr_doc_ids else "",
        )
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:2000]
        log.exception("lightrag_sync_failed", doc_id=doc_id, error=err)
        async with factory() as session:
            doc = await session.get(Document, doc_id)
            if doc is None:
                return
            doc.kg_status = "failed"
            doc.kg_error = err
            await session.commit()


async def delete_document_from_lightrag(
    *,
    kb_id: str,
    kg_doc_id: str = "",
    kg_track_id: str = "",
    strict: bool = False,
) -> bool:
    """Remove a document from LightRAG Server.

    Interactive document deletion historically treated graph cleanup as best
    effort.  Account/KB purge passes ``strict=True`` so it never claims that
    private data has been erased while an external graph copy remains.  Callers
    can retry a strict failure safely because the LightRAG delete API is
    idempotent for a known document id.
    """
    settings = get_settings()
    client = get_lightrag_client()
    if not client.enabled or not settings.lightrag_enabled:
        return True
    ids: list[str] = []
    if kg_doc_id:
        ids.append(kg_doc_id)
    elif kg_track_id:
        ids.extend(
            await client.resolve_doc_ids_from_track(kb_id=kb_id, track_id=kg_track_id)
        )
    if not ids:
        return True
    try:
        await client.delete_documents(kb_id=kb_id, doc_ids=ids)
        log.info("lightrag_delete_done", kb_id=kb_id, doc_ids=ids)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("lightrag_delete_failed", kb_id=kb_id, error=str(exc)[:500])
        if strict:
            raise
        return False
