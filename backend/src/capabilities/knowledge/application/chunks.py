"""Knowledge chunk-management use cases — SQL source of truth + vector sync.

Ingest and manual chunk ops both flow through here so counts, indices, and
vector payloads stay aligned.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.vector.embedding import embed, embed_batch
from src.capabilities.knowledge.domain.chunker import chunk_text_by_strategy, normalize_chunk_strategy
from src.capabilities.knowledge.domain.models import Chunk, Document, KB

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserEmbeddingConfig

log = structlog.get_logger()

DEFAULT_CHUNK_TARGET = 1500
DEFAULT_CHUNK_MAX_SIZE = 1800
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_CHUNK_STRATEGY = "recursive"


def chunk_uuid(doc_id: str, idx: int) -> str:
    """Stable UUID per (doc_id, idx) so re-ingest upserts instead of duplicating."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{doc_id}/{idx}"))


def resolve_chunk_params(kb: KB, doc: Document | None = None) -> tuple[int, int, int]:
    """Document overrides win; else KB defaults; else module defaults."""
    target = (
        (doc.chunk_target if doc and doc.chunk_target else None)
        or kb.chunk_target
        or DEFAULT_CHUNK_TARGET
    )
    max_size = (
        (doc.chunk_max_size if doc and doc.chunk_max_size else None)
        or kb.chunk_max_size
        or DEFAULT_CHUNK_MAX_SIZE
    )
    overlap = (
        (doc.chunk_overlap if doc and doc.chunk_overlap else None)
        or kb.chunk_overlap
        or DEFAULT_CHUNK_OVERLAP
    )
    return int(target), int(max_size), int(overlap)


def resolve_chunk_strategy(kb: KB, doc: Document | None = None) -> str:
    """Document strategy override wins; else KB default; else recursive."""
    strategy = (
        (doc.chunk_strategy if doc and doc.chunk_strategy else None)
        or kb.chunk_strategy
        or DEFAULT_CHUNK_STRATEGY
    )
    return normalize_chunk_strategy(strategy)


def chunk_document_text(kb: KB, doc: Document, text: str) -> list[str]:
    target, max_size, overlap = resolve_chunk_params(kb, doc)
    strategy = resolve_chunk_strategy(kb, doc)
    return chunk_text_by_strategy(
        text,
        strategy=strategy,
        target=target,
        max_size=max_size,
        overlap=overlap,
    )


def _chunk_payload(kb: KB, doc: Document, chunk: Chunk) -> dict:
    target, max_size, overlap = resolve_chunk_params(kb, doc)
    return {
        "doc_id": doc.id,
        "kb_id": doc.kb_id,
        "chunk_idx": chunk.chunk_idx,
        "text": chunk.text,
        "filename": doc.filename,
        "source_type": doc.source_type,
        "source_url": doc.source_url or "",
        "chunk_strategy": resolve_chunk_strategy(kb, doc),
        "chunk_target": target,
        "chunk_max_size": max_size,
        "chunk_overlap": overlap,
        "enabled": chunk.enabled,
        "doc_enabled": bool(getattr(doc, "enabled", True)),
    }


async def delete_vector_points(store, collection_name: str, point_ids: list[str]) -> None:
    if not point_ids:
        return
    if hasattr(store, "delete_by_ids"):
        await store.delete_by_ids(collection_name, point_ids)


async def clear_document_chunks(
    session: AsyncSession,
    store,
    collection_name: str,
    doc_id: str,
) -> None:
    """Remove all chunk rows + vector points for one document."""
    rows = (
        await session.execute(select(Chunk.id).where(Chunk.doc_id == doc_id))
    ).scalars().all()
    if rows and hasattr(store, "delete_by_ids"):
        await delete_vector_points(store, collection_name, list(rows))
    elif hasattr(store, "delete_by_filter"):
        await store.delete_by_filter(collection_name, {"doc_id": doc_id})
    await session.execute(delete(Chunk).where(Chunk.doc_id == doc_id))


async def renumber_chunk_indices(session: AsyncSession, doc_id: str) -> None:
    chunks = (
        await session.execute(
            select(Chunk).where(Chunk.doc_id == doc_id).order_by(Chunk.chunk_idx, Chunk.created_at)
        )
    ).scalars().all()
    for i, ch in enumerate(chunks):
        ch.chunk_idx = i


async def sync_vectors_for_chunks(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    chunks: list[Chunk],
    embedding_cfg: "UserEmbeddingConfig | None",
) -> None:
    if not chunks:
        return
    if not hasattr(store, "upsert"):
        raise RuntimeError("vector store does not support upsert")
    texts = [c.text for c in chunks]
    vectors = await embed_batch(texts, cfg=embedding_cfg)
    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"embedding count mismatch: {len(vectors)} != {len(chunks)} chunks"
        )
    points = [
        {
            "id": ch.id,
            "vector": vec,
            "payload": _chunk_payload(kb, doc, ch),
        }
        for ch, vec in zip(chunks, vectors, strict=True)
    ]
    await store.upsert(points, collection_name=kb.collection_name)


async def sync_chunk_payloads_only(
    session: AsyncSession | None,
    store,
    kb: KB,
    doc: Document,
    chunks: list[Chunk],
    *,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
) -> None:
    """Update vector payloads without re-embedding (enable/disable toggles).

    Reuses existing vectors from the store. Chunks missing in the store are
    re-embedded only when ``embedding_cfg`` is provided.
    """
    if not chunks:
        return
    if not hasattr(store, "upsert"):
        raise RuntimeError("vector store does not support upsert")

    chunk_ids = [c.id for c in chunks]
    existing: dict[str, dict] = {}
    if hasattr(store, "get_points_by_ids"):
        for pt in await store.get_points_by_ids(kb.collection_name, chunk_ids):
            existing[str(pt["id"])] = pt

    points: list[dict] = []
    missing: list[Chunk] = []
    for ch in chunks:
        pt = existing.get(ch.id)
        vec = (pt or {}).get("vector") or []
        if vec:
            points.append(
                {
                    "id": ch.id,
                    "vector": vec,
                    "payload": _chunk_payload(kb, doc, ch),
                }
            )
        else:
            missing.append(ch)

    if points:
        await store.upsert(points, collection_name=kb.collection_name)

    if missing:
        if embedding_cfg is None:
            log.warning(
                "chunk_payload_sync_missing_vectors",
                doc_id=doc.id,
                chunk_ids=[c.id for c in missing],
            )
            return
        await sync_vectors_for_chunks(
            session, store, kb, doc, missing, embedding_cfg
        )


async def persist_ingested_chunks(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    chunk_texts: list[str],
    embedding_cfg: "UserEmbeddingConfig | None",
) -> int:
    """Replace all chunks for a document after parse+split. Used by ingest."""
    await clear_document_chunks(session, store, kb.collection_name, doc.id)

    chunks: list[Chunk] = []
    for i, text in enumerate(chunk_texts):
        ch = Chunk(
            id=chunk_uuid(doc.id, i),
            doc_id=doc.id,
            kb_id=kb.id,
            chunk_idx=i,
            text=text,
            char_count=len(text),
            enabled=True,
        )
        session.add(ch)
        chunks.append(ch)
    await session.flush()

    await sync_vectors_for_chunks(session, store, kb, doc, chunks, embedding_cfg)
    return len(chunks)


async def upsert_single_chunk_vector(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    chunk: Chunk,
    embedding_cfg: "UserEmbeddingConfig | None",
) -> None:
    vec = await embed(chunk.text, cfg=embedding_cfg)
    await store.upsert(
        [
            {
            "id": chunk.id,
            "vector": vec,
            "payload": _chunk_payload(kb, doc, chunk),
        }
    ],
        collection_name=kb.collection_name,
    )


def _chunk_list_filters(
    doc_id: str,
    *,
    q: str | None = None,
    enabled: bool | None = None,
):
    stmt = select(Chunk).where(Chunk.doc_id == doc_id)
    if q and q.strip():
        stmt = stmt.where(Chunk.text.ilike(f"%{q.strip()}%"))
    if enabled is not None:
        stmt = stmt.where(Chunk.enabled == enabled)
    return stmt


async def list_document_chunks(
    session: AsyncSession,
    doc_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    enabled: bool | None = None,
) -> tuple[list[Chunk], int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    base = _chunk_list_filters(doc_id, q=q, enabled=enabled)
    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()
    rows = (
        await session.execute(
            base.order_by(Chunk.chunk_idx)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), int(total)


async def backfill_chunks_from_vector_store(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
) -> int:
    """Import legacy vector-store chunks into the SQL `chunks` table.

    Documents ingested before v4 only wrote vectors + `documents.chunks_count`;
    the chunks table was empty. This reads existing Milvus/Qdrant payloads and
    creates Chunk rows so the management UI can display/edit them without a full
    re-ingest.
    """
    if not hasattr(store, "list_by_filter"):
        return 0
    try:
        points = await store.list_by_filter(
            kb.collection_name, {"doc_id": doc.id}, limit=5000
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "chunks_backfill_vector_read_failed",
            doc_id=doc.id,
            kb_id=kb.id,
            error=str(exc)[:500],
        )
        return 0
    if not points:
        return 0

    def _idx(p: dict) -> int:
        payload = p.get("payload") or {}
        try:
            return int(payload.get("chunk_idx", 0))
        except (TypeError, ValueError):
            return 0

    points.sort(key=_idx)
    created = 0
    for p in points:
        pid = str(p.get("id") or "")
        payload = p.get("payload") or {}
        text = (payload.get("text") or "").strip()
        if not pid or not text:
            continue
        idx = _idx(p)
        enabled_raw = payload.get("enabled", True)
        enabled = enabled_raw is not False and enabled_raw != "false" and enabled_raw != 0
        existing = await session.get(Chunk, pid)
        if existing is not None:
            continue
        session.add(
            Chunk(
                id=pid,
                doc_id=doc.id,
                kb_id=kb.id,
                chunk_idx=idx,
                text=text,
                char_count=len(text),
                enabled=enabled,
            )
        )
        created += 1
    if created:
        await renumber_chunk_indices(session, doc.id)
        doc.chunks_count = (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc.id)
            )
        ).scalar_one()
        await session.commit()
        log.info(
            "chunks_backfilled",
            doc_id=doc.id,
            kb_id=kb.id,
            created=created,
        )
    return created


async def list_document_chunks_with_backfill(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    enabled: bool | None = None,
) -> tuple[list[Chunk], int]:
    """List chunks; auto-backfill from vector store when SQL table is empty."""
    rows, total = await list_document_chunks(
        session, doc.id, page=page, page_size=page_size, q=q, enabled=enabled
    )
    unfiltered = not (q and q.strip()) and enabled is None
    if unfiltered and total == 0 and (doc.chunks_count or 0) > 0 and doc.status == "done":
        backfilled = await backfill_chunks_from_vector_store(session, store, kb, doc)
        if backfilled:
            rows, total = await list_document_chunks(
                session,
                doc.id,
                page=page,
                page_size=page_size,
                q=q,
                enabled=enabled,
            )
    return rows, total


async def batch_set_chunks_enabled(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    chunk_ids: list[str],
    *,
    enabled: bool,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
) -> list[Chunk]:
    """Enable or disable multiple chunks and sync vector payloads."""
    if not chunk_ids:
        return []
    if not hasattr(store, "upsert"):
        raise RuntimeError("vector store does not support upsert")

    unique_ids = list(dict.fromkeys(chunk_ids))
    rows = (
        await session.execute(
            select(Chunk).where(
                Chunk.doc_id == doc.id,
                Chunk.id.in_(unique_ids),
            )
        )
    ).scalars().all()
    if not rows:
        return []

    changed: list[Chunk] = []
    for ch in rows:
        if ch.enabled != enabled:
            ch.enabled = enabled
            changed.append(ch)

    if changed:
        await sync_chunk_payloads_only(
            session, store, kb, doc, changed, embedding_cfg=embedding_cfg
        )
    return list(rows)


async def sync_document_vector_payloads(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
) -> int:
    """Re-upsert all chunk vectors after document-level fields change (e.g. enabled)."""
    rows = (
        await session.execute(
            select(Chunk).where(Chunk.doc_id == doc.id).order_by(Chunk.chunk_idx)
        )
    ).scalars().all()
    if not rows:
        return 0
    await sync_chunk_payloads_only(
        session, store, kb, doc, list(rows), embedding_cfg=embedding_cfg
    )
    return len(rows)


async def batch_set_all_document_chunks_enabled(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    *,
    enabled: bool,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
) -> int:
    """Enable or disable every chunk in a document."""
    rows = (
        await session.execute(select(Chunk).where(Chunk.doc_id == doc.id))
    ).scalars().all()
    if not rows:
        return 0
    changed: list[Chunk] = []
    for ch in rows:
        if ch.enabled != enabled:
            ch.enabled = enabled
            changed.append(ch)
    if changed:
        await sync_chunk_payloads_only(
            session, store, kb, doc, changed, embedding_cfg=embedding_cfg
        )
    return len(changed)


async def delete_single_chunk(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    chunk: Chunk,
) -> None:
    if hasattr(store, "delete_by_ids"):
        await delete_vector_points(store, kb.collection_name, [chunk.id])
    await session.delete(chunk)
    await session.flush()
    await renumber_chunk_indices(session, doc.id)
    doc.chunks_count = (
        await session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc.id)
        )
    ).scalar_one()
    kb.chunks_count = max(
        0,
        (kb.chunks_count or 0) - 1,
    )


async def split_chunk(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    chunk: Chunk,
    offset: int,
    embedding_cfg: "UserEmbeddingConfig | None",
) -> tuple[Chunk, Chunk]:
    text = chunk.text or ""
    if offset <= 0 or offset >= len(text):
        raise ValueError("offset must be between 1 and len(text)-1")
    left_text = text[:offset].strip()
    right_text = text[offset:].strip()
    if not left_text or not right_text:
        raise ValueError("split would produce an empty chunk")

    old_id = chunk.id
    await delete_vector_points(store, kb.collection_name, [old_id])
    await session.delete(chunk)
    await session.flush()

    left = Chunk(
        id=str(uuid.uuid4()),
        doc_id=doc.id,
        kb_id=kb.id,
        chunk_idx=0,
        text=left_text,
        char_count=len(left_text),
        enabled=True,
    )
    right = Chunk(
        id=str(uuid.uuid4()),
        doc_id=doc.id,
        kb_id=kb.id,
        chunk_idx=0,
        text=right_text,
        char_count=len(right_text),
        enabled=True,
    )
    session.add(left)
    session.add(right)
    await session.flush()
    await renumber_chunk_indices(session, doc.id)
    await session.refresh(left)
    await session.refresh(right)

    await sync_vectors_for_chunks(
        session, store, kb, doc, [left, right], embedding_cfg
    )
    doc.chunks_count = (
        await session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc.id)
        )
    ).scalar_one()
    kb.chunks_count = (kb.chunks_count or 0) + 1
    return left, right


async def merge_chunks(
    session: AsyncSession,
    store,
    kb: KB,
    doc: Document,
    chunk_a: Chunk,
    chunk_b: Chunk,
    embedding_cfg: "UserEmbeddingConfig | None",
) -> Chunk:
    if chunk_a.doc_id != doc.id or chunk_b.doc_id != doc.id:
        raise ValueError("chunks must belong to the same document")
    if chunk_a.id == chunk_b.id:
        raise ValueError("cannot merge a chunk with itself")
    first, second = (
        (chunk_a, chunk_b) if chunk_a.chunk_idx <= chunk_b.chunk_idx else (chunk_b, chunk_a)
    )
    if second.chunk_idx != first.chunk_idx + 1:
        raise ValueError("chunks must be adjacent")

    merged_text = f"{first.text}\n\n{second.text}".strip()
    await delete_vector_points(store, kb.collection_name, [first.id, second.id])
    await session.delete(first)
    await session.delete(second)
    await session.flush()

    merged = Chunk(
        id=str(uuid.uuid4()),
        doc_id=doc.id,
        kb_id=kb.id,
        chunk_idx=first.chunk_idx,
        text=merged_text,
        char_count=len(merged_text),
        enabled=True,
    )
    session.add(merged)
    await session.flush()
    await renumber_chunk_indices(session, doc.id)
    await session.refresh(merged)
    await upsert_single_chunk_vector(session, store, kb, doc, merged, embedding_cfg)

    doc.chunks_count = (
        await session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc.id)
        )
    ).scalar_one()
    kb.chunks_count = max(0, (kb.chunks_count or 0) - 1)
    return merged
