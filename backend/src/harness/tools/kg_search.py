"""Knowledge-graph recall tool — LightRAG Server context only.

Runs alongside ``search_kb`` (dense + BM25). Uses ``only_need_context`` so
LangGraph ``reason`` still owns the final answer.
"""
from __future__ import annotations

import logging
from typing import Any

from src.harness.context import estimate_tokens, truncate_text_to_token_budget
from src.capabilities.knowledge.graph.lightrag_client import get_lightrag_client
from src.settings import get_settings
from src.harness.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)

# Share the RAG budget with search_kb; keep KG portion smaller by default.
KG_CONTEXT_TOKEN_CAP = 2_500


class KGSearchTool(Tool):
    name = "search_kg"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用于知识图谱召回的查询（实体关系 / 多跳问题更合适）。",
            },
            "limit": {
                "type": "integer",
                "description": "图谱 top_k（实体或关系数），默认取服务端配置。",
                "default": 12,
            },
        },
        "required": ["query"],
    }

    def __init__(self, kb_id: str, kb_name: str = "") -> None:
        self.kb_id = kb_id
        self.kb_name = kb_name or kb_id
        self.description = (
            f"在知识库「{self.kb_name}」的知识图谱中召回实体/关系上下文"
            f"（LightRAG Server）。与 search_kb 互补：本工具偏关系与多跳，"
            f"search_kb 偏原文段落。"
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        import time

        start = time.perf_counter()
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(text="", latency_ms=0, error="query is empty")

        default_limit = int(getattr(get_settings(), "lightrag_kg_top_k", 12) or 12)
        try:
            limit = int(kwargs.get("limit") or default_limit)
        except (TypeError, ValueError):
            limit = default_limit
        limit = max(1, min(limit, 60))

        # Agenora-owned graph records are the product contract and carry
        # evidence back to a document.  Prefer them over LightRAG's opaque
        # context whenever a migrated/backfilled KB has a relevant relation.
        from src.capabilities.knowledge.graph.service import graph_context_for_query

        try:
            built_in_context = await graph_context_for_query(
                kb_id=self.kb_id, query=query, limit=limit
            )
        except Exception as exc:  # noqa: BLE001 - retain LightRAG during migration failures
            log.warning("agenora graph query failed kb_id=%s err=%r", self.kb_id, exc)
            built_in_context = ""
        if built_in_context:
            latency_ms = int((time.perf_counter() - start) * 1000)
            text = f"[KG / Agenora]\n{built_in_context}"
            if estimate_tokens(text) > KG_CONTEXT_TOKEN_CAP:
                text = truncate_text_to_token_budget(text, KG_CONTEXT_TOKEN_CAP)
            return ToolResult(
                text=text,
                latency_ms=latency_ms,
                raw={"kb_id": self.kb_id, "provider": "agenora", "chars": len(text)},
            )

        settings = get_settings()
        client = get_lightrag_client()
        if not client.enabled or not settings.lightrag_enabled:
            return ToolResult(
                text="",
                latency_ms=0,
                error="LightRAG Server 未配置（LIGHTRAG_BASE_URL）",
            )

        try:
            context = await client.query_context(
                kb_id=self.kb_id,
                query=query,
                mode=settings.lightrag_query_mode,
                top_k=limit,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - start) * 1000)
            log.warning("search_kg failed kb_id=%s err=%r", self.kb_id, exc)
            return ToolResult(text="", latency_ms=latency_ms, error=str(exc)[:800])

        text = (context or "").strip()
        if text and estimate_tokens(text) > KG_CONTEXT_TOKEN_CAP:
            text = truncate_text_to_token_budget(text, KG_CONTEXT_TOKEN_CAP)
        if text:
            text = f"[KG / LightRAG]\n{text}"

        latency_ms = int((time.perf_counter() - start) * 1000)
        return ToolResult(
            text=text,
            latency_ms=latency_ms,
            raw={"kb_id": self.kb_id, "mode": settings.lightrag_query_mode, "chars": len(text)},
        )
