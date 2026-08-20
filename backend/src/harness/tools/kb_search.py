"""LangGraph adapter for the product-owned knowledge retrieval service.

Actual vector recall, hybrid search, reranking and relevance admission live in
``capabilities.knowledge.application.retrieval``. This adapter only converts
structured, untrusted evidence into the current harness tool envelope and
applies its model-context budget.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.capabilities.knowledge.application.retrieval import (
    KnowledgeRetrievalResult,
    retrieve_knowledge_evidence,
)
from src.capabilities.knowledge.domain.models import KB
from src.harness.context import RAG_RESERVE, estimate_tokens, truncate_text_to_token_budget
from src.harness.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserEmbeddingConfig, UserRerankerConfig


# This is specific to the current prompt allocator. Other adapters can receive
# the same structured result and choose their own bounded context allocation.
MAX_RAG_RESULT_TOKENS = RAG_RESERVE


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
                "description": "返回经相关性准入后的 top-k 证据，默认 3。",
                "default": 3,
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
        self._kb = kb
        self.kb_id = kb.id
        self.kb_name = kb.name
        self.embedding_cfg = embedding_cfg
        self.reranker_cfg = reranker_cfg
        description = f"。{kb.description}" if kb.description else ""
        self.description = (
            f"在用户的知识库「{self.kb_name}」中做向量检索{description}。"
            "任何用户问题如果可能在该 KB 里能找到答案，都应优先调用此工具。"
            "传 query (中文 / 英文均可)，返回 top-k 相关文本 chunks，基于 chunks 内容作答，不要编造。"
        )

    async def retrieve(self, query: str, limit: int = 3) -> KnowledgeRetrievalResult:
        """Return runtime-neutral RAG evidence for this already-bound KB."""
        return await retrieve_knowledge_evidence(
            kb=self._kb,
            query=query,
            limit=limit,
            embedding_cfg=self.embedding_cfg,
            reranker_cfg=self.reranker_cfg,
        )

    def format_result(self, result: KnowledgeRetrievalResult, *, query: str) -> ToolResult:
        """Preserve the old tool text/raw shape for existing graph consumers."""
        if result.error:
            return ToolResult(text="", latency_ms=0, error=result.error)

        assessment = result.assessment
        if not result.evidence:
            return ToolResult(
                text=(
                    f"知识库「{self.kb_name}」中没有找到与「{query}」相关的内容。"
                    f"（候选最高相关度 {assessment.max_score:.3f}，准入阈值 {assessment.min_dense_score:.3f}）"
                ),
                latency_ms=0,
                raw={
                    "hits": 0,
                    "kb_id": self.kb_id,
                    "results": [],
                    "candidate_hits": assessment.candidate_count,
                    "max_score": assessment.max_score,
                    "min_dense_score": assessment.min_dense_score,
                    "retrieval_status": assessment.status,
                },
            )

        blocks: list[str] = []
        structured: list[dict[str, Any]] = []
        used_tokens = 0
        for index, evidence in enumerate(result.evidence, start=1):
            header = f"[chunk {index}] 来源: {evidence.filename}  相关度: {evidence.score:.3f}\n"
            separator_tokens = estimate_tokens("\n\n---\n\n") if blocks else 0
            remaining = MAX_RAG_RESULT_TOKENS - used_tokens - separator_tokens
            if remaining <= estimate_tokens(header):
                break
            block = header + evidence.text
            if estimate_tokens(block) > remaining:
                block = header + truncate_text_to_token_budget(
                    evidence.text, remaining - estimate_tokens(header)
                )
            blocks.append(block)
            used_tokens += separator_tokens + estimate_tokens(block)
            structured.append(evidence.ui_payload())

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
                "truncated": len(blocks) < len(result.evidence),
                "results": structured,
                "candidate_hits": assessment.candidate_count,
                "max_score": assessment.max_score,
                "min_dense_score": assessment.min_dense_score,
                "retrieval_status": assessment.status,
            },
        )

    async def execute(self, query: str, limit: int = 3) -> ToolResult:
        return self.format_result(await self.retrieve(query=query, limit=limit), query=query)


class MultiKBSearchTool(Tool):
    """One ACL-scoped capability that fans retrieval out to selected KBs."""

    name = "search_kb"
    input_schema = KBSearchTool.input_schema

    def __init__(self, tools: list[KBSearchTool]) -> None:
        if len(tools) < 2:
            raise ValueError("MultiKBSearchTool requires at least two KBs")
        self._tools = tools
        names = "、".join(tool.kb_name for tool in tools)
        self.description = f"在本轮已选择的多个知识库（{names}）中并行检索，并保留每条证据所属的知识库。"

    async def execute(self, query: str, limit: int = 3) -> ToolResult:
        retrievals = await asyncio.gather(
            *(tool.retrieve(query=query, limit=limit) for tool in self._tools)
        )
        blocks: list[str] = []
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        candidate_hits = 0
        max_score = 0.0
        for tool, retrieval in zip(self._tools, retrievals, strict=True):
            result = tool.format_result(retrieval, query=query)
            if result.error:
                errors.append(f"{tool.kb_name}: {result.error}")
                continue
            raw = result.raw if isinstance(result.raw, dict) else {}
            candidate_hits += int(raw.get("candidate_hits") or 0)
            max_score = max(max_score, float(raw.get("max_score") or 0.0))
            for row in raw.get("results") or []:
                if isinstance(row, dict):
                    rows.append({**row, "kb_id": tool.kb_id, "kb_name": tool.kb_name})
            if raw.get("results"):
                blocks.append(f"[知识库：{tool.kb_name}]\n{result.text}")
        return ToolResult(
            text="\n\n---\n\n".join(blocks),
            latency_ms=0,
            raw={
                "hits": len(rows),
                "kb_id": None,
                "kb_ids": [tool.kb_id for tool in self._tools],
                "results": rows,
                "candidate_hits": candidate_hits,
                "max_score": max_score,
                "retrieval_status": "hit" if rows else "miss",
            },
            error="; ".join(errors) if errors and not rows else None,
        )
