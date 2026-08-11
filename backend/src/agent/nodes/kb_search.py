"""KB search node: parallel vector search with opportunistic KG fallback."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.agent.state import AgentState
from src.observability import traced
from src.safety.prompt_injection import (
    enrich_filtered_rag_chunks,
    filter_untrusted_rag_text,
)
from src.settings import get_settings
from src.tools.base import ToolRegistry, ToolResult
from src.tools.citations import citations_from_tool_raw, merge_citations

from .constants import (
    DEFAULT_KB_SEARCH_LIMIT,
    MAX_KB_REWRITE_QUERIES,
    _KB_STRONG_HIT_SCORE,
    _KG_NEED_HINTS,
)

log = logging.getLogger(__name__)


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


def _kb_context_has_strong_hit(context_items: list[dict[str, Any]]) -> bool:
    """True when any parallel KB search returned a strong dense similarity hit."""
    for item in context_items:
        if item.get("error"):
            continue
        try:
            if float(item.get("max_score") or 0.0) >= _KB_STRONG_HIT_SCORE:
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
        return {**state, "kb_context": "", "kb_search_done": True}

    bounded_queries = queries[:MAX_KB_REWRITE_QUERIES]

    async def _run_search(idx: int, item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        query = str(item.get("query") or "").strip()
        try:
            limit = int(item.get("limit") or DEFAULT_KB_SEARCH_LIMIT)
        except (TypeError, ValueError):
            limit = DEFAULT_KB_SEARCH_LIMIT
        args = {"query": query, "limit": max(1, min(limit, 10))}
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
            # removed before they become ``kb_context`` so indirect prompt
            # injection cannot ride along as trusted retrieval evidence.
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
    kb_strong = _kb_context_has_strong_hit(context_only)

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
    turn_citations = list(state.get("citations") or [])
    rag_suspicious_chunks = int(state.get("rag_suspicious_chunks") or 0)
    prompt_reasons = list(state.get("prompt_injection_reasons") or [])
    rag_filtered_chunks = list(state.get("rag_filtered_chunks") or [])
    for tool_result, context_item in pairs:
        tool_log.append(tool_result)
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

    if kg_tool_result is not None:
        tool_log.append(kg_tool_result)
        rag_suspicious_chunks += int(kg_tool_result.get("suspicious_count") or 0)
        prompt_reasons.extend(kg_tool_result.get("suspicious_reasons") or [])
        rag_filtered_chunks.extend(kg_filtered_chunks)
        if kg_block:
            context_blocks.append(kg_block)

    if rag_filtered_chunks:
        _log_filtered_chunks(rag_filtered_chunks)

    next_prompt_risk = state.get("prompt_injection_risk") or "low"
    if rag_suspicious_chunks and next_prompt_risk == "low":
        next_prompt_risk = "medium"

    return {
        **state,
        "kb_queries": bounded_queries,
        "kb_context": "\n\n".join(context_blocks),
        "kb_search_done": True,
        "tool_call_log": tool_log,
        "citations": turn_citations,
        "rag_suspicious_chunks": rag_suspicious_chunks,
        "rag_filtered_chunks": rag_filtered_chunks,
        "prompt_injection_risk": next_prompt_risk,
        "prompt_injection_reasons": sorted(set(prompt_reasons)),
    }
