"""KB vector search tool — generic per-KB RAG.

Construction:
    KBSearchTool(kb=<KB row>, embedding_cfg=<UserEmbeddingConfig | None>,
                 reranker_cfg=<UserRerankerConfig | None>)
    binds the tool to one KB collection so its description can include the KB
    name/description (helps the LLM decide when to invoke it) and `execute(query)`
    doesn't need a kb_id arg. embedding_cfg routes query embedding through the
    user's configured provider (None = env fallback). reranker_cfg (v3-M4) opts
    the user into a second-stage cross-encoder rerank pass — when set, search
    over-fetches 4x candidates and the reranker picks the final top-K. System
    KBs (the curated travel demo) always bypass the reranker regardless of
    user setting, to keep demo behavior stable.

Returned text format is one chunk per block, separated by `---`, with filename
and similarity score inline so the agent can cite sources.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

import httpx

from src.infra.embedding import embed
from src.infra.reranker import rerank
from src.conversations.context import RAG_RESERVE, estimate_tokens, truncate_text_to_token_budget
from src.infra.vector_store import QdrantStore, get_store
from src.kb.models import KB
from src.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from src.settings_user import UserEmbeddingConfig, UserRerankerConfig


log = logging.getLogger(__name__)

# v3-M4: when reranker is enabled we over-fetch candidates to give the
# cross-encoder more material to choose from. 4x is the industry default;
# capped at 30 so a misbehaving caller can't blow up the upstream quota.
_RERANK_OVERFETCH_MULTIPLIER = 4
_RERANK_OVERFETCH_CAP = 30
# The chat allocator reserves this capacity for retrieved knowledge. Enforcing
# it at the tool boundary prevents one large document from consuming the whole
# prompt before the next planning step can apply its final context budget.
MAX_RAG_RESULT_TOKENS = RAG_RESERVE


def _chunk_enabled(hit: dict) -> bool:
    """Skip chunks disabled at chunk or document level."""
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
    if not detail:
        detail = exc.__class__.__name__
    return detail


class KBSearchTool(Tool):
    name = "search_kb"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用于在知识库中检索的查询字符串。具体、关键词清晰最好。",
            },
            "limit": {
                "type": "integer",
                "description": "返回 top-k 数，默认 5。",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        kb: KB,
        embedding_cfg: "UserEmbeddingConfig | None" = None,
        reranker_cfg: "UserRerankerConfig | None" = None,
    ) -> None:
        self.kb_id = kb.id
        self.kb_name = kb.name
        self.kb_description = kb.description or ""
        self.collection_name = kb.collection_name
        self.embedding_cfg = embedding_cfg
        # v3-M4: System KBs (curated travel demo) bypass reranker — their
        # 20-chunk dataset has been hand-tuned via MMR + city filter in v2-M7
        # and we want demo behavior stable regardless of user reranker setting.
        self.reranker_cfg = None if bool(getattr(kb, "is_system", False)) else reranker_cfg
        # v3-M3: owner-controlled. Passed through to hybrid_search as
        # group_by_field="doc_id" so each document contributes at most one
        # chunk to top-k. No-op if the collection doesn't support hybrid.
        self.grouping_enabled = bool(getattr(kb, "grouping_enabled", False))
        # Compose a description that tells the LLM what's in this KB so it
        # knows when calling search_kb makes sense.
        desc_part = f"。{self.kb_description}" if self.kb_description else ""
        self.description = (
            f"在用户的知识库「{self.kb_name}」中做向量检索{desc_part}。"
            f"任何用户问题如果可能在该 KB 里能找到答案，都应优先调用此工具。"
            f"传 query (中文 / 英文均可)，返回 top-k 相关文本 chunks，"
            f"基于 chunks 内容作答，不要编造。"
        )

    async def execute(self, query: str, limit: int = 5) -> ToolResult:
        if not query or not query.strip():
            return ToolResult(text="", latency_ms=0, error="query is empty")

        try:
            vec = await embed(query.strip(), cfg=self.embedding_cfg)
        except Exception as exc:  # noqa: BLE001
            log.warning("kb_search.embed_failed kb_id=%s err=%r", self.kb_id, exc)
            return ToolResult(
                text="",
                latency_ms=0,
                error=f"embedding 调用失败: {_describe_error(exc)}",
            )

        try:
            store = get_store()
            if not hasattr(store, "search") or not self.collection_name:
                return ToolResult(
                    text="", latency_ms=0, error="KB search requires a multi-collection backend (qdrant or milvus)"
                )
            # v3-M3: prefer hybrid (dense + BM25) if the collection was built
            # with the hybrid schema. Falls back to dense-only for legacy
            # collections and Qdrant. RRF picks the top-N members; per-chunk
            # `score` is still cosine similarity so the v2-M6 prompt's 3-tier
            # threshold logic continues to work unchanged.
            original_limit = max(1, min(int(limit) if limit else 5, 20))
            # v3-M4: when reranker is enabled, over-fetch so the cross-encoder
            # has more candidates to discriminate over.
            fetch_limit = (
                min(original_limit * _RERANK_OVERFETCH_MULTIPLIER, _RERANK_OVERFETCH_CAP)
                if self.reranker_cfg
                else original_limit
            )
            supports_hybrid = (
                hasattr(store, "hybrid_search")
                and hasattr(store, "collection_supports_hybrid")
                and await store.collection_supports_hybrid(self.collection_name)
            )
            if supports_hybrid:
                hits = await store.hybrid_search(
                    query_vector=vec,
                    query_text=query.strip(),
                    collection_name=self.collection_name,
                    limit=fetch_limit,
                    group_by="doc_id" if self.grouping_enabled else None,
                )
            else:
                hits = await store.search(
                    vec,
                    collection_name=self.collection_name,
                    limit=fetch_limit,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("kb_search.vector_failed kb_id=%s err=%r", self.kb_id, exc)
            return ToolResult(
                text="",
                latency_ms=0,
                error=f"向量检索失败: {_describe_error(exc)}",
            )

        # v3-M4: cross-encoder rerank pass. Reorders top-N candidates; on
        # failure, fall back to first-stage order so chat doesn't break.
        # IMPORTANT: hit["score"] stays cosine — reranker only reorders.
        # Latency guard: skip rerank when the first-stage top hit is already strong.
        from src.settings import get_settings as _get_settings

        skip_rerank_ge = float(
            getattr(_get_settings(), "kb_rerank_skip_if_score_ge", 0.7) or 0.0
        )
        top_score = 0.0
        for hit in hits:
            try:
                top_score = max(top_score, float(hit.get("score") or 0.0))
            except (TypeError, ValueError):
                continue
        should_rerank = (
            self.reranker_cfg
            and len(hits) >= 2
            and not (skip_rerank_ge > 0 and top_score >= skip_rerank_ge)
        )
        if should_rerank:
            texts = [(h.get("payload") or {}).get("text", "") or "" for h in hits]
            try:
                reordered = await rerank(
                    query.strip(),
                    texts,
                    top_n=original_limit,
                    cfg=self.reranker_cfg,
                )
                if reordered:
                    hits = [hits[idx] for idx, _ in reordered if 0 <= idx < len(hits)]
                    log.info(
                        "kb_search.reranked",
                        extra={
                            "kb_id": self.kb_id,
                            "fetch_limit": fetch_limit,
                            "top_n": len(hits),
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "kb_search.rerank_failed kb_id=%s err=%s — falling back to dense order",
                    self.kb_id,
                    exc,
                )
        elif self.reranker_cfg and skip_rerank_ge > 0 and top_score >= skip_rerank_ge:
            log.info(
                "kb_search.rerank_skipped_strong_hit kb_id=%s top_score=%.3f",
                self.kb_id,
                top_score,
            )

        # Trim to caller's requested limit (defensive: the rerank path already
        # returns at most top_n, but over-fetched hits without rerank need it).
        hits = [h for h in hits if _chunk_enabled(h)]
        hits = hits[:original_limit]

        if not hits:
            return ToolResult(
                text=f"知识库「{self.kb_name}」中没有找到与「{query}」相关的内容。",
                latency_ms=0,
                raw={"hits": 0, "kb_id": self.kb_id, "results": []},
            )

        # Format: per-chunk block with source filename + score for citation.
        # Structured `results` mirror only chunks that actually entered the
        # returned text (token-budget trimmed), so UI cards match evidence.
        blocks: list[str] = []
        structured: list[dict[str, Any]] = []
        used_tokens = 0
        for i, c in enumerate(hits, start=1):
            p = c.get("payload", {}) or {}
            filename = p.get("filename", "(unknown)")
            text = (p.get("text") or "").strip()
            score = c.get("score", 0.0)
            header = f"[chunk {i}] 来源: {filename}  相关度: {score:.3f}\n"
            separator_tokens = estimate_tokens("\n\n---\n\n") if blocks else 0
            remaining = MAX_RAG_RESULT_TOKENS - used_tokens - separator_tokens
            if remaining <= estimate_tokens(header):
                break
            block = header + text
            if estimate_tokens(block) > remaining:
                block = header + truncate_text_to_token_budget(
                    text, remaining - estimate_tokens(header)
                )
            blocks.append(block)
            used_tokens += separator_tokens + estimate_tokens(block)
            try:
                score_f = float(score)
            except (TypeError, ValueError):
                score_f = 0.0
            structured.append(
                {
                    "filename": filename,
                    "score": score_f,
                    "doc_id": p.get("doc_id"),
                    "text_preview": text[:240],
                }
            )

        if not blocks:
            return ToolResult(
                text=f"知识库「{self.kb_name}」中命中了内容，但结果超过上下文预算。请缩小查询范围。",
                latency_ms=0,
                raw={"hits": 0, "kb_id": self.kb_id, "truncated": True, "results": []},
            )

        return ToolResult(
            text="\n\n---\n\n".join(blocks),
            latency_ms=0,
            raw={
                "hits": len(blocks),
                "kb_id": self.kb_id,
                "truncated": len(blocks) < len(hits),
                "results": structured,
            },
        )
