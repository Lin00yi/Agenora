"""KB search node: parallel vector search with opportunistic KG fallback."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.harness.contracts.state import AgentState, RetrievedEvidence
from src.harness.context import RAG_RESERVE, estimate_tokens, truncate_text_to_token_budget
from src.harness.context.rag.assess import assessment_from_tool_raw, merge_assessments
from src.harness.context.rag.policy import resolve_kb_retrieval_policy
from src.platform.observability import traced
from src.harness.policy.prompt_injection import (
    enrich_filtered_rag_chunks,
    filter_untrusted_rag_text,
)
from src.settings import get_settings
from src.harness.tools.base import ToolRegistry, ToolResult
from src.harness.tools.citations import citations_from_tool_raw, merge_citations

from .constants import (
    MAX_KB_REWRITE_QUERIES,
    _KG_NEED_HINTS,
)

log = logging.getLogger(__name__)


def _bound_aggregated_rag_context(
    blocks: list[str], *, token_budget: int = RAG_RESERVE
) -> str:
    """Keep all parallel KB/KG evidence inside one per-turn token budget.

    ``KBSearchTool`` caps an individual call, but query expansion can make up
    to three calls and KG adds another source.  The agent consumes their merged
    text, so enforcing the cap only at the tool boundary is insufficient.
    """
    remaining = max(0, int(token_budget))
    kept: list[str] = []
    for block in blocks:
        text = (block or "").strip()
        if not text or remaining <= 0:
            break
        separator_tokens = estimate_tokens("\n\n") if kept else 0
        budget_for_block = remaining - separator_tokens
        if budget_for_block <= 0:
            break
        if estimate_tokens(text) > budget_for_block:
            clipped = truncate_text_to_token_budget(
                text,
                budget_for_block,
                suffix="\n[其余检索内容因本轮 RAG 预算省略]",
            )
            if clipped:
                kept.append(clipped)
            break
        kept.append(text)
        remaining -= separator_tokens + estimate_tokens(text)
    return "\n\n".join(kept)


def _bound_retrieved_evidence(
    items: list[RetrievedEvidence], *, token_budget: int = RAG_RESERVE
) -> list[RetrievedEvidence]:
    """Bound evidence without losing source metadata for the final prompt.

    The old flattened context was capped after source headers had been added.
    Apply the same per-turn cap to the structured representation, clipping only
    an item's text and never silently dropping its provenance fields.
    """
    remaining = max(0, int(token_budget))
    kept: list[RetrievedEvidence] = []
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text or remaining <= 0:
            break
        cost = estimate_tokens(text)
        if cost > remaining:
            clipped = truncate_text_to_token_budget(
                text,
                remaining,
                suffix="\n[其余检索内容因本轮 RAG 预算省略]",
            )
            if clipped:
                kept.append({**item, "text": clipped})
            break
        kept.append({**item, "text": text})
        remaining -= cost
    return kept


def _kb_evidence_items(
    *, query: str, text: str, tool_raw: Any
) -> list[RetrievedEvidence]:
    """Map formatted KB chunks back to their structured search metadata."""
    blocks = [block.strip() for block in (text or "").split("\n\n---\n\n") if block.strip()]
    raw_results = tool_raw.get("results") if isinstance(tool_raw, dict) else []
    raw_results = raw_results if isinstance(raw_results, list) else []
    kb_id = tool_raw.get("kb_id") if isinstance(tool_raw, dict) else None
    evidence: list[RetrievedEvidence] = []
    for index, block in enumerate(blocks, start=1):
        meta = raw_results[index - 1] if index <= len(raw_results) else {}
        meta = meta if isinstance(meta, dict) else {}
        score_raw = meta.get("score")
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        doc_id = str(meta.get("doc_id") or "").strip() or None
        title = str(meta.get("filename") or "").strip() or None
        evidence.append(
            {
                "id": f"kb:{doc_id or query}:{index}",
                "source_type": "kb",
                "query": query,
                "text": block,
                "document_id": doc_id,
                "chunk_id": str(index),
                "title": title,
                "score": score,
                "kb_id": str(kb_id) if kb_id else None,
            }
        )
    return evidence


def _query_needs_kg(text: str) -> bool:
    """Heuristic: KG helps relation / multi-hop questions more than listing queries."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    return any(hint in lowered for hint in _KG_NEED_HINTS)


def _max_score_from_tool_raw(raw: Any) -> float:
    if not isinstance(raw, dict):
        return 0.0
    best = 0.0
    for item in raw.get("results") or []:
        if not isinstance(item, dict):
            continue
        try:
            best = max(best, float(item.get("score") or 0.0))
        except (TypeError, ValueError):
            continue
    return best


def _kb_context_has_strong_hit(
    context_items: list[dict[str, Any]], *, threshold: float
) -> bool:
    """True when any parallel KB search returned a strong dense similarity hit."""
    for item in context_items:
        if item.get("error"):
            continue
        try:
            if float(item.get("max_score") or 0.0) >= threshold:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _log_filtered_chunks(chunks: list[dict[str, Any]]) -> None:
    for row in chunks:
        log.warning(
            "rag_chunk_filtered channel=%s kb_id=%s doc_id=%s filename=%s "
            "level=%s reasons=%s score=%s preview=%s",
            row.get("channel"),
            row.get("kb_id"),
            row.get("doc_id"),
            row.get("filename"),
            row.get("level"),
            row.get("reasons"),
            row.get("score"),
            (row.get("preview") or "")[:120],
        )


@traced("kb_search")
async def kb_search_node(
    state: AgentState,
    *,
    registry: ToolRegistry,
    emit,
) -> AgentState:
    """Execute rewritten KB queries in parallel and merge them into state."""
    if state.get("kb_search_done"):
        return state

    queries = state.get("kb_queries") or []
    if not queries:
        return {
            **state,
            "kb_context": "",
            "retrieved_evidence": [],
            "kb_search_done": True,
            "retrieval_assessment": merge_assessments([]).as_dict(),
        }

    bounded_queries = queries[:MAX_KB_REWRITE_QUERIES]
    retrieval_policy = resolve_kb_retrieval_policy()

    async def _run_search(idx: int, item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        query = str(item.get("query") or "").strip()
        try:
            limit = int(item.get("limit") or retrieval_policy.final_limit)
        except (TypeError, ValueError):
            limit = retrieval_policy.final_limit
        args = {"query": query, "limit": max(1, min(limit, retrieval_policy.final_limit))}
        tool_id = f"kb_search_{idx}_{int(time.time() * 1000)}"

        await emit({"event": "tool_start", "id": tool_id, "name": "search_kb", "input": args})
        result = await registry.call("search_kb", args)
        citations = (
            citations_from_tool_raw("search_kb", result.raw)
            if result.error is None
            else []
        )
        await emit(
            {
                "event": "tool_end",
                "id": tool_id,
                "name": "search_kb",
                "latency_ms": result.latency_ms,
                "ok": result.error is None,
                "error": result.error,
                "citations": citations,
            }
        )
        tool_result = {
            "id": tool_id,
            "name": "search_kb",
            "input": args,
            "result": result.text if result.error is None else f"[tool error] {result.error}",
            "latency_ms": result.latency_ms,
            "error": "yes" if result.error is not None else None,
            "citations": citations,
        }
        filtered_text = tool_result["result"]
        suspicious_count = 0
        suspicious_reasons: list[str] = []
        filtered_chunks: list[dict[str, Any]] = []
        if result.error is None:
            # KB text is user-controlled document data. Suspicious blocks are
            # removed before they become ``retrieved_evidence`` so indirect
            # prompt injection cannot ride along as model-visible evidence.
            filtered_text, suspicious_count, suspicious_reasons, details = (
                filter_untrusted_rag_text(tool_result["result"] or "")
            )
            tool_result["result"] = filtered_text
            filtered_chunks = enrich_filtered_rag_chunks(
                details,
                channel="kb",
                query=query,
                tool_raw=result.raw,
            )
        context_item = {
            "query": query,
            "limit": args["limit"],
            "text": filtered_text,
            "error": result.error,
            "latency_ms": result.latency_ms,
            "max_score": _max_score_from_tool_raw(result.raw),
            "suspicious_count": suspicious_count,
            "suspicious_reasons": suspicious_reasons,
            "filtered_chunks": filtered_chunks,
            "tool_raw": result.raw,
        }
        return tool_result, context_item

    settings = get_settings()
    kg_top_k = max(1, min(int(getattr(settings, "lightrag_kg_top_k", 12) or 12), 60))
    kg_hard_timeout = max(1.0, float(getattr(settings, "lightrag_timeout_s", 20.0) or 20.0))
    kg_soft_wait = max(0.0, float(getattr(settings, "lightrag_kg_soft_wait_s", 0.0) or 0.0))
    kg_only_when_needed = bool(getattr(settings, "lightrag_kg_only_when_needed", True))

    kg_tool_id = f"kg_search_{int(time.time() * 1000)}"
    primary_q = str(bounded_queries[0].get("query") or "").strip() if bounded_queries else ""
    kg_args = {"query": primary_q, "limit": kg_top_k}
    kg_registered = "search_kg" in registry.names() and bool(primary_q)
    # Relation-like questions start KG in parallel; listing/factoid queries wait
    # and only fall back to KG when vector hits are weak.
    kg_eager = kg_registered and (
        not kg_only_when_needed or _query_needs_kg(primary_q)
    )

    kg_task: asyncio.Task[Any] | None = None
    kg_started_at = 0.0
    if kg_eager:
        await emit(
            {"event": "tool_start", "id": kg_tool_id, "name": "search_kg", "input": kg_args}
        )
        kg_started_at = time.perf_counter()
        kg_task = asyncio.create_task(registry.call("search_kg", kg_args))

    pairs = await asyncio.gather(
        *[_run_search(idx, item) for idx, item in enumerate(bounded_queries, start=1)]
    )

    context_only = [ctx for _, ctx in pairs]
    kb_strong = _kb_context_has_strong_hit(
        context_only, threshold=retrieval_policy.kg_skip_if_dense_score_ge
    )

    # Opportunistic KG: non-relational query + weak KB → run KG once after vector search.
    if kg_task is None and kg_registered and not kb_strong:
        await emit(
            {"event": "tool_start", "id": kg_tool_id, "name": "search_kg", "input": kg_args}
        )
        kg_started_at = time.perf_counter()
        kg_task = asyncio.create_task(registry.call("search_kg", kg_args))

    kg_tool_result: dict[str, Any] | None = None
    kg_block = ""
    kg_filtered_chunks: list[dict[str, Any]] = []
    if kg_task is not None:
        # Strong KB evidence → abandon KG immediately (soft_wait defaults to 0).
        budget = kg_soft_wait if kb_strong else kg_hard_timeout
        elapsed = time.perf_counter() - kg_started_at
        remaining = max(0.05, budget - elapsed) if budget > 0 else 0.05
        kg_result: ToolResult | None = None
        timed_out = False
        try:
            if budget <= 0:
                raise asyncio.TimeoutError()
            kg_result = await asyncio.wait_for(asyncio.shield(kg_task), timeout=remaining)
        except asyncio.TimeoutError:
            timed_out = True
            kg_task.cancel()
            try:
                await kg_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            latency_ms = int((time.perf_counter() - kg_started_at) * 1000)
            kg_result = ToolResult(
                text="",
                latency_ms=latency_ms,
                error=(
                    "kg_search skipped: strong KB hits already available"
                    if kb_strong
                    else f"kg_search timed out after {latency_ms}ms"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - kg_started_at) * 1000)
            kg_result = ToolResult(text="", latency_ms=latency_ms, error=str(exc)[:800])

        assert kg_result is not None
        await emit(
            {
                "event": "tool_end",
                "id": kg_tool_id,
                "name": "search_kg",
                "latency_ms": kg_result.latency_ms,
                "ok": kg_result.error is None,
                "error": kg_result.error,
                "citations": [],
            }
        )
        kg_tool_result = {
            "id": kg_tool_id,
            "name": "search_kg",
            "input": kg_args,
            "result": (
                kg_result.text
                if kg_result.error is None
                else f"[tool error] {kg_result.error}"
            ),
            "latency_ms": kg_result.latency_ms,
            "error": "yes" if kg_result.error is not None else None,
            "citations": [],
            "timed_out": timed_out,
        }
        if kg_result.error is None and (kg_result.text or "").strip():
            filtered_kg, kg_sus_count, kg_sus_reasons, kg_details = filter_untrusted_rag_text(
                kg_result.text or ""
            )
            kg_tool_result["suspicious_count"] = kg_sus_count
            kg_tool_result["suspicious_reasons"] = kg_sus_reasons
            kg_filtered_chunks = enrich_filtered_rag_chunks(
                kg_details,
                channel="kg",
                query=primary_q,
                tool_raw=kg_result.raw,
            )
            kg_tool_result["filtered_chunks"] = kg_filtered_chunks
            if filtered_kg.strip():
                kg_block = (
                    f"## KG search query: {primary_q}\n"
                    f"latency_ms: {kg_result.latency_ms}\n{filtered_kg}"
                )

    tool_log = list(state.get("tool_call_log") or [])
    context_blocks: list[str] = []
    evidence_items: list[RetrievedEvidence] = []
    turn_citations = list(state.get("citations") or [])
    rag_suspicious_chunks = int(state.get("rag_suspicious_chunks") or 0)
    prompt_reasons = list(state.get("prompt_injection_reasons") or [])
    rag_filtered_chunks = list(state.get("rag_filtered_chunks") or [])
    assessments = []
    for tool_result, context_item in pairs:
        tool_log.append(tool_result)
        part = assessment_from_tool_raw(context_item.get("tool_raw"))
        if part is not None:
            assessments.append(part)
        turn_citations = merge_citations(turn_citations, tool_result.get("citations") or [])
        rag_suspicious_chunks += int(context_item.get("suspicious_count") or 0)
        prompt_reasons.extend(context_item.get("suspicious_reasons") or [])
        chunk_rows = list(context_item.get("filtered_chunks") or [])
        rag_filtered_chunks.extend(chunk_rows)
        header = (
            f"## KB search query: {context_item['query']}\n"
            f"limit: {context_item['limit']}; latency_ms: {context_item['latency_ms']}"
        )
        if context_item["error"]:
            context_blocks.append(f"{header}\nERROR: {context_item['error']}")
        else:
            context_blocks.append(f"{header}\n{context_item['text']}")
            evidence_items.extend(
                _kb_evidence_items(
                    query=str(context_item["query"]),
                    text=str(context_item["text"]),
                    tool_raw=context_item.get("tool_raw"),
                )
            )

    if kg_tool_result is not None:
        tool_log.append(kg_tool_result)
        rag_suspicious_chunks += int(kg_tool_result.get("suspicious_count") or 0)
        prompt_reasons.extend(kg_tool_result.get("suspicious_reasons") or [])
        rag_filtered_chunks.extend(kg_filtered_chunks)
        if kg_block:
            context_blocks.append(kg_block)
            evidence_items.append(
                {
                    "id": f"kg:{primary_q}",
                    "source_type": "kg",
                    "query": primary_q,
                    "text": kg_block,
                    "document_id": None,
                    "chunk_id": None,
                    "title": "LightRAG",
                    "score": None,
                    "kb_id": None,
                }
            )

    if rag_filtered_chunks:
        _log_filtered_chunks(rag_filtered_chunks)

    next_prompt_risk = state.get("prompt_injection_risk") or "low"
    if rag_suspicious_chunks and next_prompt_risk == "low":
        next_prompt_risk = "medium"

    injection_mode = str(getattr(settings, "rag_injection_mode", "user_evidence") or "").strip().lower()
    legacy_kb_context = (
        _bound_aggregated_rag_context(context_blocks)
        if injection_mode == "legacy_system"
        else ""
    )
    return {
        **state,
        "kb_queries": bounded_queries,
        "kb_context": legacy_kb_context,
        "retrieved_evidence": _bound_retrieved_evidence(evidence_items),
        "retrieval_assessment": merge_assessments(assessments).as_dict(),
        "kb_search_done": True,
        "tool_call_log": tool_log,
        "citations": turn_citations,
        "rag_suspicious_chunks": rag_suspicious_chunks,
        "rag_filtered_chunks": rag_filtered_chunks,
        "prompt_injection_risk": next_prompt_risk,
        "prompt_injection_reasons": sorted(set(prompt_reasons)),
    }
