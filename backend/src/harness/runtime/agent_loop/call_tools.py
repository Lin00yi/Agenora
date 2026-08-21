"""Call-tools node: execute pending tool calls concurrently."""
from __future__ import annotations

import asyncio
import time
from typing import Any, TYPE_CHECKING

from src.harness.contracts.state import AgentState
from src.platform.observability import traced
from src.harness.policy.tool_guard import is_tool_allowed
from src.harness.mcp.policies import supports_high_risk_policy
from src.harness.tools.base import ToolRegistry
from src.harness.tools.citations import citations_from_tool_raw, merge_citations
from src.harness.tools.web_search import _format_web_results, select_web_result_raw
from src.settings import get_settings

from .constants import (
    MAX_CONCURRENT_TOOL_CALLS_PER_STEP,
    MAX_SEARCH_KB_CALLS_PER_STEP,
    MAX_TOOL_CALLS_PER_TURN,
    MAX_TOOL_RESULT_TOKENS_PER_CALL,
    MAX_TOOL_RESULT_TOKENS_PER_STEP,
)
from .tool_results import compact_tool_results


def _latest_user_text(messages: list[dict[str, Any]] | None) -> str:
    """Return the last human text without trusting model-generated tool args."""
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = "\n".join(
                str(block.get("text", "")).strip()
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
            if text:
                return text
    return ""


def _refund_confirmation_error(name: str, args: dict[str, Any], messages: list[dict[str, Any]] | None) -> str | None:
    """Enforce a human turn boundary before the irreversible MCP tool runs."""
    if name != "confirm_refund":
        return None
    approval_id = str(args.get("approval_id") or "").strip()
    expected = f"确认退款 {approval_id}" if approval_id else ""
    actual = _latest_user_text(messages)
    if not expected or actual != expected or str(args.get("confirmation_text") or "").strip() != expected:
        return "退款必须由用户在最新一条消息精确确认（确认退款 <approval_id>）；本次未执行。"
    return None


def _high_risk_mcp_error(
    name: str,
    args: dict[str, Any],
    messages: list[dict[str, Any]] | None,
    *,
    tool: Any | None,
) -> str | None:
    """Apply Host policy to catalogued high-risk MCP tools before dispatch."""
    if getattr(tool, "risk", None) != "high_risk_write":
        return _refund_confirmation_error(name, args, messages)
    policy_id = getattr(tool, "policy_id", None)
    if supports_high_risk_policy(policy_id):
        return _refund_confirmation_error(name, args, messages)
    return "该高风险操作没有可执行的宿主确认策略，本次未执行。"

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserLLMConfig


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
    settings = get_settings()
    max_tool_calls = max(
        1, int(getattr(settings, "agent_max_tool_calls_per_turn", MAX_TOOL_CALLS_PER_TURN))
    )
    max_concurrent_calls = max(
        1,
        int(
            getattr(
                settings,
                "agent_max_concurrent_tool_calls",
                MAX_CONCURRENT_TOOL_CALLS_PER_STEP,
            )
        ),
    )
    max_result_per_call = max(
        1,
        int(
            getattr(
                settings,
                "agent_tool_result_max_tokens_per_call",
                MAX_TOOL_RESULT_TOKENS_PER_CALL,
            )
        ),
    )
    max_result_per_step = max(
        1,
        int(
            getattr(
                settings,
                "agent_tool_result_max_tokens_per_step",
                MAX_TOOL_RESULT_TOKENS_PER_STEP,
            )
        ),
    )

    # Count actual external dispatches, rather than model requests. A blocked
    # call consumes no side-effect budget, but cannot trigger an unbounded
    # fan-out either because each graph turn is still iteration-bounded.
    previous_tool_calls = max(
        0,
        int(state.get("tool_call_count") or len(state.get("tool_call_log") or [])),
    )
    reserved_tool_calls = 0
    budget_lock = asyncio.Lock()
    call_semaphore = asyncio.Semaphore(max_concurrent_calls)

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
        nonlocal reserved_tool_calls
        name = tc["name"]
        args = tc.get("input") or {}
        started_at_ms = int(time.time() * 1000)
        tool = registry.get(name)
        display = tool.trace_metadata() if tool is not None else None
        confirmation_error = _high_risk_mcp_error(
            name,
            args,
            state.get("messages"),
            tool=tool,
        )
        if confirmation_error:
            await emit(
                {
                    "event": "tool_blocked",
                    "id": tc["id"],
                    "name": name,
                    "input": args,
                    "reason": confirmation_error,
                    **({"display": display} if display else {}),
                }
            )
            return {"type": "tool_result", "tool_use_id": tc["id"], "content": f"[blocked by safety] {confirmation_error}", "is_error": True}
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
                    **({"display": display} if display else {}),
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
                    **({"display": display} if display else {}),
                }
            )
            return {
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": f"[blocked by safety] {reason}",
                "is_error": True,
            }
        # Reserve only after permission, confirmation and per-tool policy
        # checks pass. Invalid calls must not consume the useful-work budget.
        async with budget_lock:
            if previous_tool_calls + reserved_tool_calls >= max_tool_calls:
                budget_exhausted = True
            else:
                reserved_tool_calls += 1
                budget_exhausted = False
        if budget_exhausted:
            reason = f"本轮工具调用总额度已达上限（{max_tool_calls} 次），本次未执行。"
            await emit(
                {
                    "event": "tool_blocked",
                    "id": tc["id"],
                    "name": name,
                    "input": args,
                    "reason": reason,
                    **({"display": display} if display else {}),
                }
            )
            return {
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": f"[blocked by runtime budget] {reason}",
                "is_error": True,
                "executed": False,
            }
        await emit(
            {
                "event": "tool_start",
                "id": tc["id"],
                "name": name,
                "input": args,
                **({"display": display} if display else {}),
            }
        )

        async with call_semaphore:
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
                    **({"display": display} if display else {}),
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
                "display": display,
            "t0": started_at_ms,
            "executed": True,
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
                **(
                    {"display": registry.get("web_search").trace_metadata()}
                    if registry.get("web_search") is not None
                    else {}
                ),
            }
        )

    for result in results:
        raw = result.get("raw")
        result["is_final_result"] = bool(
            isinstance(raw, dict) and raw.get("final_result") and not result.get("is_error")
        )
    output_budget = compact_tool_results(
        results,
        max_tokens_per_call=max_result_per_call,
        max_tokens_per_step=max_result_per_step,
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
                "latency_ms": r.get("latency_ms"),
                "t0": r.get("t0"),
                "error": "yes" if r.get("is_error") else None,
                "citations": cites,
                "result_truncated": bool(r.get("result_truncated")),
                **({"display": r["display"]} if r.get("display") else {}),
            }
        )

    messages = list(state.get("messages") or [])
    # `raw`, citations, UI descriptors and timing are runtime-only.  Do not
    # carry them into checkpointed/model-visible history; provider adapters
    # need only the canonical tool-result block fields.
    model_results = [
        {
            "type": "tool_result",
            "tool_use_id": r["tool_use_id"],
            "content": r["content"],
            "is_error": bool(r.get("is_error")),
        }
        for r in results
    ]
    messages.append({"role": "user", "content": model_results})

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
        "tool_call_count": previous_tool_calls + sum(
            1 for result in results if result.get("executed")
        ),
        "tool_call_limit": max_tool_calls,
        "tool_result_budget": output_budget.to_state(),
    }
