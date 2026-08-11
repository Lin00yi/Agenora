"""Call-tools node: execute pending tool calls concurrently."""
from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from src.agent.state import AgentState
from src.observability import traced
from src.safety.tool_guard import is_tool_allowed
from src.tools.base import ToolRegistry
from src.tools.citations import citations_from_tool_raw, merge_citations

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
    search_kb_calls = 0
    for tc in pending:
        if tc.get("name") != "search_kb":
            continue
        search_kb_calls += 1
        if search_kb_calls > MAX_SEARCH_KB_CALLS_PER_STEP:
            blocked_tool_call_ids[tc["id"]] = (
                f"search_kb call limit exceeded: max {MAX_SEARCH_KB_CALLS_PER_STEP} per step"
            )

    async def _run(tc: dict[str, Any]) -> dict[str, Any]:
        name = tc["name"]
        args = tc.get("input") or {}
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
        }

    results = await asyncio.gather(*[_run(tc) for tc in pending])

    tool_log = list(state.get("tool_call_log") or [])
    turn_citations = list(state.get("citations") or [])
    for tc, r in zip(pending, results, strict=False):
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
    }
