"""Structured private-KB retrieval independent of any agent runtime.

The caller must resolve the KB rows through the product's ACL boundary before
calling this service.  It intentionally returns structured, untrusted evidence
instead of agent prompt text. Runtime adapters can apply their own context
budget and event transport without duplicating recall, reranking, or relevance
admission rules.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx

from src.platform.vector import get_vector_store as get_store
from src.platform.vector.embedding import embed
from src.platform.vector.reranker import rerank
from src.settings import Settings, get_settings

if TYPE_CHECKING:
    from src.capabilities.knowledge.domain.models import KB
    from src.capabilities.settings.domain.models import UserEmbeddingConfig, UserRerankerConfig


log = logging.getLogger(__name__)
RetrievalStatus = Literal["empty", "miss", "hit"]


@dataclass(frozen=True)
class RetrievalAssessment:
    status: RetrievalStatus
    candidate_count: int
    admitted_count: int
    max_score: float
    min_dense_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_count": self.candidate_count,
            "admitted_count": self.admitted_count,
            "max_score": self.max_score,
            "min_dense_score": self.min_dense_score,
        }


@dataclass(frozen=True)
class KBRetrievalPolicy:
    candidate_limit: int
    final_limit: int
    min_dense_score: float
    kg_skip_if_dense_score_ge: float


@dataclass(frozen=True)
class RetrievedEvidence:
    """One admitted chunk. Content is untrusted source material, never policy."""

    filename: str
    text: str
    score: float
    doc_id: str | None

    def ui_payload(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "score": self.score,
            "doc_id": self.doc_id,
            "text_preview": self.text[:240],
        }


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    """Transport-neutral result for one ACL-scoped knowledge base."""

    kb_id: str
    kb_name: str
    evidence: tuple[RetrievedEvidence, ...]
    assessment: RetrievalAssessment
    error: str | None = None

    @property
    def status(self) -> RetrievalStatus:
        return self.assessment.status


def normalized_score(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _display_score(value: Any) -> float:
    """Keep the stored cosine value for citations while admission normalizes it."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def admit_hits(
    hits: list[dict[str, Any]],
    *,
    min_dense_score: float,
    final_limit: int,
    is_enabled: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], RetrievalAssessment]:
    """Filter disabled chunks, then admit only evidence above the score floor."""
    enabled = [hit for hit in hits if is_enabled(hit)] if is_enabled else list(hits)
    candidate_count = len(enabled)
    max_score = max((normalized_score(hit.get("score")) for hit in enabled), default=0.0)
    admitted = [
        hit for hit in enabled if normalized_score(hit.get("score")) >= min_dense_score
    ][: max(0, int(final_limit))]
    if candidate_count == 0:
        status: RetrievalStatus = "empty"
    elif not admitted:
        status = "miss"
    else:
        status = "hit"
    return admitted, RetrievalAssessment(
        status=status,
        candidate_count=candidate_count,
        admitted_count=len(admitted),
        max_score=max_score,
        min_dense_score=float(min_dense_score),
    )


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return max(minimum, min(default, maximum))


def _bounded_score(value: object, *, default: float) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def resolve_kb_retrieval_policy(settings: Settings | None = None) -> KBRetrievalPolicy:
    """Resolve bounded server-owned limits for every private-KB runtime."""
    current = settings or get_settings()
    final_limit = _bounded_int(
        current.kb_retrieval_final_limit, default=3, minimum=1, maximum=10
    )
    return KBRetrievalPolicy(
        candidate_limit=max(
            final_limit,
            _bounded_int(current.kb_retrieval_candidate_limit, default=6, minimum=1, maximum=30),
        ),
        final_limit=final_limit,
        min_dense_score=_bounded_score(current.kb_retrieval_min_dense_score, default=0.4),
        kg_skip_if_dense_score_ge=_bounded_score(
            current.kb_kg_skip_if_dense_score_ge, default=0.7
        ),
    )


def _chunk_enabled(hit: dict[str, Any]) -> bool:
    payload = hit.get("payload") or {}
    chunk_on = payload.get("enabled", True)
    if chunk_on is False or chunk_on == "false" or chunk_on == 0:
        return False
    doc_on = payload.get("doc_enabled", True)
    return doc_on is not False and doc_on != "false" and doc_on != 0


def _describe_error(exc: BaseException) -> str:
    detail = str(exc).strip()
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = (exc.response.text or "").strip()
        except Exception:  # noqa: BLE001
            body = ""
        if body and body not in detail:
            detail = f"{detail}; response={body[:300]}" if detail else body[:300]
    return detail or exc.__class__.__name__


async def retrieve_knowledge_evidence(
    *,
    kb: "KB",
    query: str,
    limit: int = 3,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
    reranker_cfg: "UserRerankerConfig | None" = None,
) -> KnowledgeRetrievalResult:
    """Retrieve structured evidence from one already-authorized KB.

    This service performs no identity lookup and must not be exposed as a
    generic ``kb_id`` endpoint. The caller must authenticate a run and select
    ACL-permitted KB rows first.
    """
    kb_id = str(kb.id)
    kb_name = str(kb.name)
    empty = RetrievalAssessment("empty", 0, 0, 0.0, 0.0)
    if not query or not query.strip():
        return KnowledgeRetrievalResult(kb_id, kb_name, (), empty, "query is empty")

    try:
        vector = await embed(query.strip(), cfg=embedding_cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("knowledge_retrieval.embed_failed kb_id=%s err=%r", kb_id, exc)
        return KnowledgeRetrievalResult(
            kb_id, kb_name, (), empty, f"embedding 调用失败: {_describe_error(exc)}"
        )

    policy = resolve_kb_retrieval_policy()
    original_limit = min(
        max(1, min(int(limit) if limit else policy.final_limit, 20)),
        policy.final_limit,
    )
    fetch_limit = max(original_limit, policy.candidate_limit)
    try:
        store = get_store()
        collection_name = str(getattr(kb, "collection_name", "") or "")
        if not hasattr(store, "search") or not collection_name:
            return KnowledgeRetrievalResult(
                kb_id,
                kb_name,
                (),
                empty,
                "KB search requires a multi-collection backend (qdrant or milvus)",
            )
        supports_hybrid = (
            hasattr(store, "hybrid_search")
            and hasattr(store, "collection_supports_hybrid")
            and await store.collection_supports_hybrid(collection_name)
        )
        if supports_hybrid:
            hits = await store.hybrid_search(
                query_vector=vector,
                query_text=query.strip(),
                collection_name=collection_name,
                limit=fetch_limit,
                group_by="doc_id" if bool(getattr(kb, "grouping_enabled", False)) else None,
            )
        else:
            hits = await store.search(vector, collection_name=collection_name, limit=fetch_limit)
    except Exception as exc:  # noqa: BLE001
        log.warning("knowledge_retrieval.vector_failed kb_id=%s err=%r", kb_id, exc)
        return KnowledgeRetrievalResult(
            kb_id, kb_name, (), empty, f"向量检索失败: {_describe_error(exc)}"
        )

    effective_reranker = None if bool(getattr(kb, "is_system", False)) else reranker_cfg
    top_score = max((normalized_score(hit.get("score")) for hit in hits), default=0.0)
    skip_rerank_ge = float(getattr(get_settings(), "kb_rerank_skip_if_score_ge", 0.7) or 0.0)
    if effective_reranker and len(hits) >= 2 and not (
        skip_rerank_ge > 0 and top_score >= skip_rerank_ge
    ):
        texts = [(hit.get("payload") or {}).get("text", "") or "" for hit in hits]
        try:
            reordered = await rerank(query.strip(), texts, top_n=original_limit, cfg=effective_reranker)
            if reordered:
                hits = [hits[index] for index, _score in reordered if 0 <= index < len(hits)]
        except Exception as exc:  # noqa: BLE001
            log.warning("knowledge_retrieval.rerank_failed kb_id=%s err=%s", kb_id, exc)
    elif effective_reranker and skip_rerank_ge > 0 and top_score >= skip_rerank_ge:
        log.info("knowledge_retrieval.rerank_skipped_strong_hit kb_id=%s top_score=%.3f", kb_id, top_score)

    hits, assessment = admit_hits(
        hits,
        min_dense_score=policy.min_dense_score,
        final_limit=original_limit,
        is_enabled=_chunk_enabled,
    )
    evidence: list[RetrievedEvidence] = []
    for hit in hits:
        payload = hit.get("payload") or {}
        evidence.append(
            RetrievedEvidence(
                filename=str(payload.get("filename") or "(unknown)"),
                text=str(payload.get("text") or "").strip(),
                score=_display_score(hit.get("score")),
                doc_id=str(payload["doc_id"]) if payload.get("doc_id") is not None else None,
            )
        )
    return KnowledgeRetrievalResult(kb_id, kb_name, tuple(evidence), assessment)
