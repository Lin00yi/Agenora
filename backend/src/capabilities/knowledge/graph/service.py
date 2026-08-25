"""Graph scans, extraction persistence, and graph read projections."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.capabilities.identity.models import User
from src.capabilities.knowledge.domain.models import Chunk, Document, KB
from src.capabilities.settings.domain.models import resolve_system_llm, resolve_user_llm_routing_configs
from src.harness.prompts.registry import PromptResolution, fallback_resolution, resolve_published_prompts
from src.harness.prompts.system import PROMPT_KEY_GRAPH_EXTRACTION
from src.platform.persistence.database import get_session_factory

from .extraction import document_content_hash, document_extraction_hash, extract_relation_candidates
from .models import GraphEntity, GraphEvidence, GraphExtractionRun, GraphRelation, GraphScan, GraphSource


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stable_id(namespace: str, *parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "/".join((namespace, *parts))))


def _normalized_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())[:255]


def _source_id_for_document(document_id: str) -> str:
    return _stable_id("agenora-graph-source", document_id)


async def ensure_graph_source(session: AsyncSession, document: Document) -> GraphSource:
    """Give every graph-enabled document a durable source configuration."""
    source_id = _source_id_for_document(document.id)
    source = await session.get(GraphSource, source_id)
    if source is None:
        source = GraphSource(
            id=source_id,
            kb_id=document.kb_id,
            document_id=document.id,
            source_type=document.source_type or "document",
            source_url=document.source_url or "",
        )
        session.add(source)
    else:
        source.source_type = document.source_type or source.source_type
        source.source_url = document.source_url or ""
    return source


async def _resolve_graph_llm(session: AsyncSession, kb: KB) -> Any | None:
    """Use the knowledge-base owner's primary model-routing target."""
    owner = await session.get(User, kb.user_id)
    routing = (
        await resolve_user_llm_routing_configs(session, owner)
        if owner is not None
        else None
    )
    return (routing.primary if routing is not None else None) or resolve_system_llm()


async def _resolve_graph_extraction_prompt(session: AsyncSession) -> PromptResolution:
    """Use a published extraction template, or keep the code default stable."""
    prompts = await resolve_published_prompts(session)
    return prompts.get(PROMPT_KEY_GRAPH_EXTRACTION, fallback_resolution(PROMPT_KEY_GRAPH_EXTRACTION))


async def request_graph_scan(
    session: AsyncSession,
    *,
    kb_id: str,
    trigger: str,
    source_id: str | None = None,
) -> tuple[GraphScan, Any]:
    """Persist a graph scan and its leased operation before doing work."""
    from src.platform.tasks import enqueue_operation

    scan = GraphScan(
        id=str(uuid.uuid4()), kb_id=kb_id, source_id=source_id, trigger=trigger, status="pending"
    )
    session.add(scan)
    await session.flush()
    job = await enqueue_operation(
        session,
        kind="scan_knowledge_graph",
        payload={"scan_id": scan.id},
        idempotency_key=f"graph-scan:{scan.id}",
        max_attempts=3,
    )
    return scan, job


async def _refresh_relation_counts(session: AsyncSession, relation_ids: set[str]) -> set[str]:
    entity_ids: set[str] = set()
    for relation_id in relation_ids:
        relation = await session.get(GraphRelation, relation_id)
        if relation is None:
            continue
        count = await session.scalar(
            select(func.count(GraphEvidence.id)).where(
                GraphEvidence.relation_id == relation_id, GraphEvidence.active.is_(True)
            )
        )
        relation.evidence_count = int(count or 0)
        relation.status = "active" if relation.evidence_count else "archived"
        if relation.evidence_count:
            relation.last_seen_at = _utcnow()
        entity_ids.update((relation.source_entity_id, relation.target_entity_id))
    for entity_id in entity_ids:
        entity = await session.get(GraphEntity, entity_id)
        if entity is None:
            continue
        count = await session.scalar(
            select(func.coalesce(func.sum(GraphRelation.evidence_count), 0)).where(
                GraphRelation.status == "active",
                or_(GraphRelation.source_entity_id == entity_id, GraphRelation.target_entity_id == entity_id),
            )
        )
        entity.evidence_count = int(count or 0)
        entity.status = "active" if entity.evidence_count else "archived"
    return entity_ids


async def remove_document_graph(session: AsyncSession, *, document_id: str) -> None:
    """Withdraw a document's evidence before its relational row is deleted."""
    relation_ids = set(
        (
            await session.execute(
                select(GraphEvidence.relation_id).where(
                    GraphEvidence.document_id == document_id, GraphEvidence.active.is_(True)
                )
            )
        ).scalars()
    )
    for evidence in (
        await session.execute(
            select(GraphEvidence).where(GraphEvidence.document_id == document_id, GraphEvidence.active.is_(True))
        )
    ).scalars():
        evidence.active = False
    await _refresh_relation_counts(session, relation_ids)
    await session.execute(delete(GraphSource).where(GraphSource.document_id == document_id))


async def _entity_for_candidate(
    session: AsyncSession, *, kb_id: str, name: str, entity_type: str, confidence: float
) -> GraphEntity:
    normalized = _normalized_name(name)
    entity_id = _stable_id("agenora-graph-entity", kb_id, entity_type, normalized)
    entity = await session.get(GraphEntity, entity_id)
    now = _utcnow()
    if entity is None:
        entity = GraphEntity(
            id=entity_id,
            kb_id=kb_id,
            canonical_name=name[:255],
            normalized_name=normalized,
            entity_type=entity_type,
            confidence=confidence,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(entity)
    else:
        entity.confidence = max(float(entity.confidence or 0), confidence)
        entity.last_seen_at = now
        entity.status = "active"
    return entity


async def extract_document_graph(document_id: str, *, scan_id: str | None = None) -> dict[str, int | str]:
    """Extract one document version, replacing only its evidence contribution."""
    factory = get_session_factory()
    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return {"skipped": "document_deleted"}
        kb = await session.get(KB, document.kb_id)
        if kb is None or not bool(kb.kg_enabled) or not (document.parsed_text or "").strip():
            return {"skipped": "graph_disabled_or_empty"}
        llm_cfg = await _resolve_graph_llm(session, kb)
        prompt_resolution = await _resolve_graph_extraction_prompt(session)
        source_text_hash = document_content_hash(document.parsed_text)
        content_hash = document_extraction_hash(
            document.parsed_text, llm_cfg=llm_cfg, prompt_digest=prompt_resolution.digest
        )
        run_id = _stable_id("agenora-graph-extraction", document.id, content_hash)
        run = await session.get(GraphExtractionRun, run_id)
        if run is not None and run.status == "done":
            return {"skipped": "already_extracted", "entities": run.entities_count, "relations": run.relations_count}
        if run is None:
            run = GraphExtractionRun(
                id=run_id,
                kb_id=kb.id,
                document_id=document.id,
                scan_id=scan_id,
                content_hash=content_hash,
                status="running",
            )
            session.add(run)
        else:
            run.scan_id = scan_id or run.scan_id
            run.status = "running"
            run.error = ""
        source_text = document.parsed_text
        filename = document.filename
        await session.commit()

    candidates, extractor, model = await extract_relation_candidates(
        text=source_text,
        document_name=filename,
        llm_cfg=llm_cfg,
        system_prompt=prompt_resolution.content,
    )

    async with factory() as session:
        document = await session.get(Document, document_id)
        run = await session.get(GraphExtractionRun, run_id)
        if document is None or run is None:
            return {"skipped": "document_deleted"}
        # Document content changed while a remote model was running. Preserve
        # the old evidence until the new content receives its own operation.
        if document_content_hash(document.parsed_text) != source_text_hash:
            run.status = "superseded"
            run.completed_at = _utcnow()
            await session.commit()
            return {"skipped": "content_changed"}

        old_relation_ids = set(
            (
                await session.execute(
                    select(GraphEvidence.relation_id).where(
                        GraphEvidence.document_id == document_id, GraphEvidence.active.is_(True)
                    )
                )
            ).scalars()
        )
        for evidence in (
            await session.execute(
                select(GraphEvidence).where(GraphEvidence.document_id == document_id, GraphEvidence.active.is_(True))
            )
        ).scalars():
            evidence.active = False

        chunk_rows = list(
            (
                await session.execute(select(Chunk).where(Chunk.doc_id == document_id).order_by(Chunk.chunk_idx))
            ).scalars()
        )
        relation_ids = set(old_relation_ids)
        entity_ids: set[str] = set()
        for candidate in candidates:
            source = await _entity_for_candidate(
                session, kb_id=document.kb_id, name=candidate.source,
                entity_type=candidate.source_type, confidence=candidate.confidence,
            )
            target = await _entity_for_candidate(
                session, kb_id=document.kb_id, name=candidate.target,
                entity_type=candidate.target_type, confidence=candidate.confidence,
            )
            entity_ids.update((source.id, target.id))
            fingerprint = f"{source.id}:{candidate.relation_type}:{target.id}"
            relation_id = _stable_id("agenora-graph-relation", document.kb_id, fingerprint)
            relation = await session.get(GraphRelation, relation_id)
            if relation is None:
                relation = GraphRelation(
                    id=relation_id, kb_id=document.kb_id, source_entity_id=source.id,
                    target_entity_id=target.id, relation_type=candidate.relation_type,
                    fingerprint=fingerprint, confidence=candidate.confidence,
                )
                session.add(relation)
            else:
                relation.confidence = max(float(relation.confidence or 0), candidate.confidence)
                relation.status = "active"
            chunk_id = next((chunk.id for chunk in chunk_rows if candidate.quote in chunk.text), None)
            evidence_id = _stable_id(
                "agenora-graph-evidence", relation_id, document.id, content_hash, candidate.quote
            )
            evidence = await session.get(GraphEvidence, evidence_id)
            if evidence is None:
                evidence = GraphEvidence(
                    id=evidence_id, kb_id=document.kb_id, relation_id=relation_id,
                    document_id=document.id, chunk_id=chunk_id, extraction_run_id=run.id,
                    quote=candidate.quote, content_hash=content_hash, active=True,
                )
                session.add(evidence)
            else:
                evidence.active = True
                evidence.chunk_id = chunk_id
                evidence.extraction_run_id = run.id
            relation_ids.add(relation_id)

        await session.flush()
        await _refresh_relation_counts(session, relation_ids)
        run.extractor = extractor
        run.extractor_model = model
        run.extractor_version = (
            f"prompt:{prompt_resolution.source}:v{prompt_resolution.version or 'code'}"
        )[:32]
        run.status = "done"
        run.entities_count = len(entity_ids)
        run.relations_count = len({relation_id for relation_id in relation_ids if relation_id not in old_relation_ids} | (relation_ids & old_relation_ids))
        run.completed_at = _utcnow()
        if scan_id:
            scan = await session.get(GraphScan, scan_id)
            if scan is not None:
                scan.documents_extracted += 1
        await session.commit()
        return {"entities": len(entity_ids), "relations": len(candidates), "run_id": run.id}


async def run_graph_scan(scan_id: str) -> dict[str, int | str]:
    """Scan one source or all current KB documents, then enqueue changed extraction."""
    from src.platform.tasks import enqueue_operation
    from src.capabilities.knowledge.application.ingestion import ingest_document

    factory = get_session_factory()
    async with factory() as session:
        scan = await session.get(GraphScan, scan_id)
        if scan is None:
            return {"skipped": "scan_deleted"}
        scan.status = "running"
        scan.started_at = _utcnow()
        kb = await session.get(KB, scan.kb_id)
        if kb is None or not bool(kb.kg_enabled):
            scan.status = "skipped"
            scan.completed_at = _utcnow()
            await session.commit()
            return {"skipped": "graph_disabled"}
        if scan.source_id:
            source = await session.get(GraphSource, scan.source_id)
            document_ids = [source.document_id] if source and source.document_id else []
        else:
            document_ids = list(
                (
                    await session.execute(
                        select(Document.id).where(
                            Document.kb_id == kb.id, Document.status == "done", Document.enabled.is_(True)
                        )
                    )
                ).scalars()
            )
        scan.documents_seen = len(document_ids)
        scan_trigger = scan.trigger
        await session.commit()

    changed = 0
    extracted_jobs = 0
    for document_id in document_ids:
        async with factory() as session:
            document = await session.get(Document, document_id)
            if document is None:
                continue
            source = await ensure_graph_source(session, document)
            is_remote = source.source_type == "url" and bool(source.source_url)
            await session.commit()
        # URL documents are rescanned via their normal ingestion path. Files
        # retain their uploaded version and are simply re-extracted when asked.
        if is_remote and scan_trigger == "schedule":
            await ingest_document(document_id, graph_scan_id=scan_id)
        async with factory() as session:
            document = await session.get(Document, document_id)
            source = await session.get(GraphSource, _source_id_for_document(document_id))
            if document is None or source is None or document.status != "done":
                continue
            llm_cfg = await _resolve_graph_llm(session, kb)
            prompt_resolution = await _resolve_graph_extraction_prompt(session)
            content_hash = document_extraction_hash(
                document.parsed_text, llm_cfg=llm_cfg, prompt_digest=prompt_resolution.digest
            )
            if source.last_content_hash == content_hash:
                source.last_scan_at = _utcnow()
                source.last_error = ""
                await session.commit()
                continue
            changed += 1
            source.last_content_hash = content_hash
            source.last_scan_at = _utcnow()
            source.last_error = ""
            if source.scan_interval_minutes > 0:
                source.next_scan_at = _utcnow() + timedelta(minutes=source.scan_interval_minutes)
            job = await enqueue_operation(
                session,
                kind="extract_graph_document",
                payload={"document_id": document_id, "scan_id": scan_id},
                idempotency_key=f"graph-extract:{document_id}:{content_hash}",
                max_attempts=3,
            )
            extracted_jobs += 1 if job.status in {"pending", "running"} else 0
            await session.commit()

    async with factory() as session:
        scan = await session.get(GraphScan, scan_id)
        if scan is not None:
            scan.documents_changed = changed
            # A scan only discovers and dispatches document extractions.  Do
            # not report it as complete until its child jobs reach a terminal
            # state; local Milvus development intentionally processes one
            # durable job at a time, so waiting here would deadlock the queue.
            if extracted_jobs:
                scan.status = "extracting"
                scan.completed_at = None
            else:
                scan.status = "done"
                scan.completed_at = _utcnow()
            await session.commit()
    return {"documents_seen": len(document_ids), "documents_changed": changed, "extraction_jobs": extracted_jobs}


async def reconcile_graph_scans(*, limit: int = 100) -> int:
    """Finalize dispatched scans only after all of their extraction jobs end.

    Scan and extraction are separate durable jobs.  This reconciliation keeps
    the user-facing scan status truthful without making the parent scan block
    the single-job local worker.
    """
    from src.platform.tasks.models import OperationJob

    factory = get_session_factory()
    finalized = 0
    async with factory() as session:
        scans = list(
            (
                await session.execute(
                    select(GraphScan)
                    .where(GraphScan.status == "extracting")
                    .order_by(GraphScan.created_at)
                    .limit(max(1, min(limit, 500)))
                )
            ).scalars()
        )
        for scan in scans:
            jobs = list(
                (
                    await session.execute(
                        select(OperationJob).where(
                            OperationJob.kind == "extract_graph_document",
                            OperationJob.payload_json.contains(f'"scan_id": "{scan.id}"'),
                        )
                    )
                ).scalars()
            )
            # The scan commits dispatched work before transitioning to this
            # state.  Keep it visible as extracting rather than racing a
            # just-created child job in another transaction.
            if not jobs or any(job.status in {"pending", "running"} for job in jobs):
                continue
            failed = [job for job in jobs if job.status == "dead_letter"]
            if failed:
                scan.status = "dead_letter"
                scan.error = (failed[0].error or "图谱关系抽取失败")[:2000]
            else:
                scan.status = "done"
                scan.error = ""
            scan.completed_at = _utcnow()
            finalized += 1
        if finalized:
            await session.commit()
    return finalized


async def enqueue_due_graph_scans(*, limit: int = 50) -> int:
    """Durably enqueue due source scans from the dedicated operation worker."""
    factory = get_session_factory()
    now = _utcnow()
    count = 0
    async with factory() as session:
        sources = list(
            (
                await session.execute(
                    select(GraphSource)
                    .where(
                        GraphSource.enabled.is_(True),
                        GraphSource.scan_interval_minutes > 0,
                        GraphSource.next_scan_at.is_not(None),
                        GraphSource.next_scan_at <= now,
                    )
                    .order_by(GraphSource.next_scan_at)
                    .limit(max(1, min(limit, 200)))
                )
            ).scalars()
        )
        for source in sources:
            # Atomic due-time claim keeps worker replicas from creating two
            # scans for the same source.  The claim and operation enqueue are
            # committed together below, so a crash leaves the source due.
            claimed = await session.execute(
                update(GraphSource)
                .where(
                    GraphSource.id == source.id,
                    GraphSource.enabled.is_(True),
                    GraphSource.next_scan_at.is_not(None),
                    GraphSource.next_scan_at <= now,
                )
                .values(next_scan_at=now + timedelta(minutes=source.scan_interval_minutes))
            )
            if not claimed.rowcount:
                continue
            await request_graph_scan(session, kb_id=source.kb_id, trigger="schedule", source_id=source.id)
            count += 1
        await session.commit()
    return count


async def graph_snapshot(
    session: AsyncSession, *, kb_id: str, query: str = "", limit: int = 120
) -> dict[str, Any]:
    """Return a bounded visual projection; clients never query Neo4j directly."""
    limit = max(1, min(int(limit), 300))
    entity_query = select(GraphEntity).where(GraphEntity.kb_id == kb_id, GraphEntity.status == "active")
    needle = _normalized_name(query)
    if needle:
        entity_query = entity_query.where(GraphEntity.normalized_name.contains(needle))
    entities = list(
        (
            await session.execute(entity_query.order_by(GraphEntity.evidence_count.desc(), GraphEntity.last_seen_at.desc()).limit(limit))
        ).scalars()
    )
    entity_ids = {entity.id for entity in entities}
    if not entity_ids:
        return {"nodes": [], "edges": [], "truncated": False}
    relations = list(
        (
            await session.execute(
                select(GraphRelation).where(
                    GraphRelation.kb_id == kb_id,
                    GraphRelation.status == "active",
                    GraphRelation.source_entity_id.in_(entity_ids),
                    GraphRelation.target_entity_id.in_(entity_ids),
                ).order_by(GraphRelation.evidence_count.desc()).limit(limit * 3)
            )
        ).scalars()
    )
    return {
        "nodes": [entity.to_public_dict() for entity in entities],
        "edges": [relation.to_public_dict() for relation in relations],
        "truncated": len(entities) >= limit,
    }


async def graph_context_for_query(*, kb_id: str, query: str, limit: int = 12) -> str:
    """Render bounded, evidence-linked Agenora graph context for the chat tool.

    This is deliberately a read projection, not a model-visible database query
    language.  It lets the application move off LightRAG's private graph
    schema while retaining that service as a fallback during migration.
    """
    terms = [term for term in re.split(r"\s+", _normalized_name(query)) if len(term) >= 2]
    if not terms:
        return ""
    factory = get_session_factory()
    async with factory() as session:
        entity_filters = [GraphEntity.normalized_name.contains(term) for term in terms[:4]]
        entities = list(
            (
                await session.execute(
                    select(GraphEntity)
                    .where(
                        GraphEntity.kb_id == kb_id,
                        GraphEntity.status == "active",
                        or_(*entity_filters),
                    )
                    .order_by(GraphEntity.evidence_count.desc(), GraphEntity.last_seen_at.desc())
                    .limit(max(1, min(limit, 40)))
                )
            ).scalars()
        )
        seed_ids = {entity.id for entity in entities}
        if not seed_ids:
            return ""
        relations = list(
            (
                await session.execute(
                    select(GraphRelation)
                    .where(
                        GraphRelation.kb_id == kb_id,
                        GraphRelation.status == "active",
                        or_(
                            GraphRelation.source_entity_id.in_(seed_ids),
                            GraphRelation.target_entity_id.in_(seed_ids),
                        ),
                    )
                    .order_by(GraphRelation.evidence_count.desc(), GraphRelation.confidence.desc())
                    .limit(max(1, min(limit, 40)))
                )
            ).scalars()
        )
        if not relations:
            return ""
        entity_ids = {identifier for relation in relations for identifier in (relation.source_entity_id, relation.target_entity_id)}
        names = {
            entity.id: entity.canonical_name
            for entity in (
                await session.execute(select(GraphEntity).where(GraphEntity.id.in_(entity_ids)))
            ).scalars()
        }
        relation_ids = [relation.id for relation in relations]
        evidence_rows = list(
            (
                await session.execute(
                    select(GraphEvidence)
                    .where(GraphEvidence.relation_id.in_(relation_ids), GraphEvidence.active.is_(True))
                    .order_by(GraphEvidence.created_at.desc())
                    .limit(len(relation_ids) * 2)
                )
            ).scalars()
        )
        evidence_by_relation: dict[str, GraphEvidence] = {}
        for evidence in evidence_rows:
            evidence_by_relation.setdefault(evidence.relation_id, evidence)
        lines = []
        for relation in relations:
            evidence = evidence_by_relation.get(relation.id)
            if evidence is None:
                continue
            source = names.get(relation.source_entity_id, "未知实体")
            target = names.get(relation.target_entity_id, "未知实体")
            quote = " ".join((evidence.quote or "").split())[:400]
            lines.append(
                f"- {source} —{relation.relation_type}→ {target} "
                f"(置信度 {float(relation.confidence or 0):.2f}; 证据：{quote})"
            )
        return "\n".join(lines)
