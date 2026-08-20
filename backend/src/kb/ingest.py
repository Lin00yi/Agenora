"""KB ingest pipeline: parse → chunk → embed → upsert.

`ingest_document(doc_id)` is the background-task entry point. It runs after
the upload endpoint has returned 200 to the client, and updates the Document
row's status as it progresses.

Lifecycle:
    pending  ─ initial state set by the upload route
    ingesting ─ this function started work
    done     ─ chunks written, counts updated
    failed   ─ `error` column populated

The function uses two short DB sessions (one to claim, one to finalize) and
does the heavy work (HTTP fetch, parsing, embedding, vector-store upsert) in between
so it doesn't hold a SQLite write lock for minutes.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from src.storage.database import get_session_factory
from src.adapters.files import get_object_storage
from src.adapters.vector import get_vector_store as get_store
from src.capabilities.knowledge.application.documents import upload_key
from src.kb.chunk_service import chunk_document_text, clear_document_chunks, persist_ingested_chunks
from src.kb.models import KB, Document
from src.kb.parsers import dispatch, parse_url

if TYPE_CHECKING:
    from src.settings_user import UserEmbeddingConfig

log = structlog.get_logger()

# Anchor the upload directory to the backend root so systemd / Docker can run
# the service with an unrelated WorkingDirectory and still find user files.
# ingest.py is at backend/src/kb/ingest.py → parents[2] = backend/
UPLOAD_BASE = Path(__file__).resolve().parents[2] / "data" / "uploads"


# ---------------------------------------------------------------------------
# Disk storage helpers
# ---------------------------------------------------------------------------
def upload_path(kb_id: str, doc_id: str, filename: str) -> Path:
    """Stable filesystem path for an uploaded file.

    Layout:  data/uploads/{kb_id}/{doc_id}.{ext}
    The doc_id (UUID) makes the filename unique and safe to write; the
    original filename is preserved separately on the Document row.
    """
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    # sanitize ext to avoid path traversal
    ext = "".join(c for c in ext if c.isalnum())[:16] or "bin"
    return UPLOAD_BASE / kb_id / f"{doc_id}.{ext}"


def save_uploaded_file(kb_id: str, doc_id: str, filename: str, content: bytes) -> Path:
    path = upload_path(kb_id, doc_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def delete_uploaded_file(kb_id: str, doc_id: str, filename: str) -> None:
    path = upload_path(kb_id, doc_id, filename)
    if path.exists():
        path.unlink()


def delete_kb_uploads(kb_id: str) -> None:
    """Recursively remove all uploads for a KB. Called from KB DELETE."""
    base = UPLOAD_BASE / kb_id
    if not base.exists():
        return
    for f in base.glob("**/*"):
        if f.is_file():
            try:
                f.unlink()
            except OSError:
                pass
    try:
        base.rmdir()
    except OSError:
        pass  # not empty / locked — leave it


# ---------------------------------------------------------------------------
# Main entry — runs as FastAPI BackgroundTask
# ---------------------------------------------------------------------------
async def ingest_document(
    doc_id: str,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
) -> None:
    """Background ingest worker.

    v3-M7: when `embedding_cfg` is None we derive it from the KB row first
    (KB-level cfg), then fall back to the KB owner's user-level cfg. Callers
    can still pass an explicit cfg to override (e.g. tests).
    """
    factory = get_session_factory()

    # ---- 1. Claim: load doc/kb, flip status → ingesting, commit, release session
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
            "embedding_model": kb.embedding_model,
            "vector_size": kb.vector_size,
        }
        # v3-M7: derive embedding cfg from KB row (then user owner) when the
        # caller didn't supply one explicitly. Loading the owner User row here
        # lets `resolve_kb_embedding` fall back through the chain.
        if embedding_cfg is None:
            from src.auth.models import User
            from src.settings_user.kb_resolvers import resolve_kb_embedding
            owner = await session.get(User, kb.user_id)
            embedding_cfg = resolve_kb_embedding(kb, owner)
        doc_snapshot = {
            "kb_id": doc.kb_id,
            "filename": doc.filename,
            "source_type": doc.source_type,
            "source_url": doc.source_url or "",
        }
        prev_chunks = doc.chunks_count or 0
        doc.status = "ingesting"
        await session.commit()

    # ---- 2. Heavy work outside the session
    new_status = "failed"
    new_chunks = 0
    error_msg = ""

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

        # Load KB for chunk params (session closed — re-open briefly or use snapshot).
        async with factory() as session:
            kb_row = await session.get(KB, kb_snapshot["id"])
            doc_row = await session.get(Document, doc_id)
            if kb_row is None or doc_row is None:
                raise ValueError("document or kb disappeared during ingest")
            doc_row.parsed_text = text
            await session.commit()
            target_kb = kb_row
            target_doc = doc_row

        chunks = chunk_document_text(target_kb, target_doc, text)
        if not chunks:
            raise ValueError("chunker produced 0 chunks")

        store = get_store()
        if not hasattr(store, "create_collection"):
            raise RuntimeError(
                "KB ingest requires a multi-collection backend (qdrant or milvus)"
            )

        async with factory() as session:
            kb_row = await session.get(KB, kb_snapshot["id"])
            doc_row = await session.get(Document, doc_id)
            if kb_row is None or doc_row is None:
                raise ValueError("document or kb disappeared during ingest")
            new_chunks = await persist_ingested_chunks(
                session,
                store,
                kb_row,
                doc_row,
                chunks,
                embedding_cfg,
            )
            doc_row.chunks_count = new_chunks
            await session.commit()

        new_status = "done"
        log.info(
            "ingest_done",
            doc_id=doc_id,
            kb_id=kb_snapshot["id"],
            chunks=new_chunks,
            collection=kb_snapshot["collection_name"],
        )
    except Exception as exc:  # noqa: BLE001
        error_msg = str(exc)[:2000]
        log.exception("ingest_failed", doc_id=doc_id, error=error_msg)

    # ---- 3. Finalize: write status + counts in a fresh session
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
                kb.chunks_count = (kb.chunks_count or 0) - prev_chunks + new_chunks
                kg_enabled = bool(getattr(kb, "kg_enabled", False))
        await session.commit()

    # ---- 4. Optional LightRAG Server sync (does not fail vector ingest)
    if new_status == "done" and kg_enabled:
        try:
            from src.kg.sync import sync_document_to_lightrag

            await sync_document_to_lightrag(doc_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("lightrag_sync_invoke_failed", doc_id=doc_id, error=str(exc)[:500])


async def delete_document_chunks(collection_name: str, doc_id: str) -> None:
    """Drop a document's chunks from vector store + SQL. Idempotent."""
    from src.storage.database import get_session_factory

    store = get_store()
    factory = get_session_factory()
    async with factory() as session:
        await clear_document_chunks(session, store, collection_name, doc_id)
        await session.commit()
