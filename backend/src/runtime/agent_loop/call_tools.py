"""Call-tools node: execute pending tool calls concurrently."""
from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from src.runtime.state import AgentState
from src.observability import traced
from src.safety.tool_guard import is_tool_allowed
from src.tools.base import ToolRegistry
from src.tools.citations import citations_from_tool_raw, merge_citations
from src.tools.web_search import _format_web_results, select_web_result_raw

from .constants import MAX_SEARCH_KB_CALLS_PER_STEP

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig


@traced("call_tools")
async def call_tools_node(
    state: AgentState,
    *,
    registry: ToolRegistry,
    emit,
    llm_cfg: "UserLLMConfig | None" = None,
    web_search_max_calls: int | None = None,
    web_search_evidence_limit: int | None = None,
) -> AgentState:
    """Execute all pending tool calls concurrently.

    v2-M8: `llm_cfg` flows through to `invoke_skill` so the report skill
    uses the user's own LLM (v2-M1) instead of always env defaults.
    """
    pending = state.get("pending_tool_calls", [])
    if not pending:
        return state
    _ = llm_cfg

    blocked_tool_call_ids: dict[str, str] = {}
    # A spent search budget is expected control flow, not a safety violation.
    # Keep it out of the user-facing tool timeline while telling the model to
    # finish from the evidence already collected.
    exhausted_web_tool_call_ids: set[str] = set()
    search_kb_calls = 0
    previous_web_calls = max(0, int(state.get("web_search_call_count") or 0))
    allowed_web_calls = previous_web_calls
    for tc in pending:
        name = tc.get("name")
        if name == "search_kb":
            search_kb_calls += 1
            if search_kb_calls > MAX_SEARCH_KB_CALLS_PER_STEP:
                blocked_tool_call_ids[tc["id"]] = (
                    f"search_kb call limit exceeded: max {MAX_SEARCH_KB_CALLS_PER_STEP} per step"
                )
        if name == "web_search" and web_search_max_calls is not None:
            if allowed_web_calls >= max(0, web_search_max_calls):
                exhausted_web_tool_call_ids.add(tc["id"])
            else:
                allowed_web_calls += 1

    async def _run(tc: dict[str, Any]) -> dict[str, Any]:
        name = tc["name"]
        args = tc.get("input") or {}
        if tc["id"] in exhausted_web_tool_call_ids:
            return {
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": (
                    "[web search budget exhausted] 本轮外网检索额度已用尽。"
                    "不要再调用 web_search；请仅基于已获得的网页证据回答。"
                    "若证据不足，请直接说明无法确认的部分。"
                ),
                "is_error": False,
                "hidden_from_trace": True,
            }
        if tc["id"] in blocked_tool_call_ids:
            reason = blocked_tool_call_ids[tc["id"]]
            await emit(
                {
                    "event": "tool_blocked",
                    "id": tc["id"],
                    "name": name,
                    "input": args,
                    "reason": reason,
                }
            )
            return {
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": f"[blocked by safety] {reason}",
                "is_error": True,
            }

        ok, reason = is_tool_allowed(
            name,
            registry.names(),
        )
        if not ok:
            await emit(
                {
                    "event": "tool_blocked",
                    "id": tc["id"],
                    "name": name,
                    "input": args,
                    "reason": reason,
                }
            )
            return {
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": f"[blocked by safety] {reason}",
                "is_error": True,
            }
        await emit({"event": "tool_start", "id": tc["id"], "name": name, "input": args})

        result = await registry.call(name, args)
        citations = (
            citations_from_tool_raw(name, result.raw) if result.error is None else []
        )
        # Successful web results are emitted after the whole-response evidence
        # budget is applied below, so the live timeline and final source cards
        # expose the same set of citations.
        if name != "web_search" or result.error is not None:
            await emit(
                {
                    "event": "tool_end",
                    "id": tc["id"],
                    "name": name,
                    "latency_ms": result.latency_ms,
                    "ok": result.error is None,
                    "error": result.error,
                    "citations": citations,
                }
            )
        return {
            "type": "tool_result",
            "tool_use_id": tc["id"],
            "content": result.text if result.error is None else f"[tool error] {result.error}",
            "is_error": result.error is not None,
            "raw": result.raw,
            "citations": citations,
            "latency_ms": result.latency_ms,
        }

    results = await asyncio.gather(*[_run(tc) for tc in pending])

    # Limit successful web evidence across the complete response, rather than
    # only per call. This shapes both the tool-result message the model sees
    # and the structured source cards persisted for the client.
    previous_web_evidence = max(0, int(state.get("web_search_evidence_count") or 0))
    remaining_web_evidence = (
        max(0, web_search_evidence_limit - previous_web_evidence)
        if web_search_evidence_limit is not None
        else None
    )
    accepted_web_evidence = 0
    web_rows: list[tuple[int, int, int]] = []
    for result_index, (tc, result) in enumerate(zip(pending, results, strict=False)):
        if (
            tc.get("name") != "web_search"
            or result.get("is_error")
            or result.get("hidden_from_trace")
        ):
            continue
        raw = result.get("raw")
        rows = raw.get("results", []) if isinstance(raw, dict) else []
        if not isinstance(rows, list):
            continue
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            try:
                quality = int(row.get("_quality") or 0)
            except (TypeError, ValueError):
                quality = 0
            web_rows.append((quality, result_index, row_index))

    selected_rows: dict[int, set[int]] = {}
    if remaining_web_evidence is None:
        for _, result_index, row_index in web_rows:
            selected_rows.setdefault(result_index, set()).add(row_index)
    else:
        for _, result_index, row_index in sorted(
            web_rows, key=lambda item: (-item[0], item[1], item[2])
        )[:remaining_web_evidence]:
            selected_rows.setdefault(result_index, set()).add(row_index)

    for result_index, (tc, result) in enumerate(zip(pending, results, strict=False)):
        if (
            tc.get("name") != "web_search"
            or result.get("is_error")
            or result.get("hidden_from_trace")
        ):
            continue
        raw = select_web_result_raw(
            result.get("raw"), indices=selected_rows.get(result_index, set())
        )
        accepted = int(raw.get("count") or 0)
        result["raw"] = raw
        result["content"] = _format_web_results(raw)
        result["citations"] = citations_from_tool_raw("web_search", raw)
        accepted_web_evidence += accepted
        await emit(
            {
                "event": "tool_end",
                "id": tc["id"],
                "name": "web_search",
                "latency_ms": result.get("latency_ms", 0),
                "ok": True,
                "error": None,
                "citations": result["citations"],
            }
        )

    tool_log = list(state.get("tool_call_log") or [])
    turn_citations = list(state.get("citations") or [])
    for tc, r in zip(pending, results, strict=False):
        if r.get("hidden_from_trace"):
            continue
        cites = r.get("citations") or []
        turn_citations = merge_citations(turn_citations, cites)
        tool_log.append(
            {
                "id": tc["id"],
                "name": tc["name"],
                "input": tc.get("input") or {},
                "result": r["content"],
                "latency_ms": 0,
                "error": "yes" if r.get("is_error") else None,
                "citations": cites,
            }
        )

    messages = list(state.get("messages") or [])
    messages.append({"role": "user", "content": results})

    final_report = state.get("final_report")
    for r in results:
        raw = r.get("raw")
        is_final_tool = isinstance(raw, dict) and bool(raw.get("final_result"))
        if is_final_tool and not r.get("is_error"):
            final_report = r["content"]
            break

    return {
        **state,
        "messages": messages,
        "pending_tool_calls": [],
        "tool_call_log": tool_log,
        "citations": turn_citations,
        "final_report": final_report,
        "web_search_call_count": allowed_web_calls,
        "web_search_evidence_count": previous_web_evidence + accepted_web_evidence,
    }
