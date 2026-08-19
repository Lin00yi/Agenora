"""System prompt composition and provider context-window budgeting."""
from __future__ import annotations

import json
from typing import Any

from src.context import (
    MAX_OUTPUT_TOKENS,
    SAFETY_RESERVE,
    context_window_for_model,
    estimate_tokens,
    truncate_text_to_token_budget,
)

from .constants import _TRUSTED_CONTEXT_SOURCES, _latest_user_text


def build_effective_system_prompt(
    base_prompt: str, messages: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]], dict[str, str]]:
    """Keep static instructions separate from user-derived context data.

    ``conversations.context`` uses internal tagged ``system`` rows only while
    assembling state.  They must not acquire provider system-message authority:
    ``reason`` carries the returned blocks in the latest user-turn data envelope
    alongside RAG evidence.  This preserves a static, cacheable system prefix.
    """
    context_blocks: dict[str, str] = {}
    conversation_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "system":
            content = message.get("content", "")
            # Only server-generated context is eligible for system-prompt
            # composition. A legacy client can still submit a ``system`` role
            # in its request body, so accepting every such message here would
            # create a prompt-injection path.
            if (
                message.get("_context_source") in _TRUSTED_CONTEXT_SOURCES
                and isinstance(content, str)
                and content.strip()
            ):
                context_blocks[str(message["_context_source"])] = content.strip()
            continue
        conversation_messages.append(message)

    return base_prompt, conversation_messages, context_blocks


def _estimate_message_tokens(message: dict[str, Any]) -> int:
    content = message.get("content", "")
    if isinstance(content, str):
        text = content
    else:
        # Tool calls and tool results are structured blocks. JSON retains their
        # complete semantics while making their allocation measurable.
        text = json.dumps(content, ensure_ascii=False, default=str)
    return estimate_tokens(text) + 6


def _trim_provider_messages(messages: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    """Retain the newest provider messages without splitting content blocks."""
    if token_budget <= 0:
        return []

    kept_reversed: list[dict[str, Any]] = []
    remaining = token_budget
    for message in reversed(messages):
        cost = _estimate_message_tokens(message)
        if cost <= remaining:
            kept_reversed.append(message)
            remaining -= cost
            continue
        if not kept_reversed and isinstance(message.get("content"), str):
            clipped = dict(message)
            clipped["content"] = truncate_text_to_token_budget(
                message["content"], max(1, remaining - 6)
            )
            kept_reversed.append(clipped)
        break

    kept = list(reversed(kept_reversed))
    # Do not start provider history with an orphaned assistant turn. If the
    # assistant is the only survivor, recover the preceding user turn (clipped)
    # so a tight budget cannot wipe the entire window.
    while kept and kept[0].get("role") == "assistant":
        if len(kept) > 1:
            kept.pop(0)
            continue
        orphan = kept[0]
        orphan_index = -1
        for i in range(len(messages) - 1, -1, -1):
            candidate = messages[i]
            if candidate is orphan or (
                candidate.get("role") == orphan.get("role")
                and candidate.get("content") == orphan.get("content")
            ):
                orphan_index = i
                break
        prior = messages[orphan_index - 1] if orphan_index > 0 else None
        if (
            prior is None
            or prior.get("role") != "user"
            or not isinstance(prior.get("content"), str)
            or not isinstance(orphan.get("content"), str)
        ):
            break
        assistant_cost = estimate_tokens(orphan["content"]) + 6
        if assistant_cost + 40 <= token_budget:
            user_msg = dict(prior)
            user_msg["content"] = truncate_text_to_token_budget(
                prior["content"], max(1, token_budget - assistant_cost - 6)
            )
            kept = [user_msg, orphan]
        else:
            user_msg = dict(prior)
            user_msg["content"] = truncate_text_to_token_budget(
                prior["content"], max(1, token_budget // 2 - 6)
            )
            used = estimate_tokens(user_msg["content"]) + 6
            asst_msg = dict(orphan)
            asst_msg["content"] = truncate_text_to_token_budget(
                orphan["content"], max(1, token_budget - used - 6)
            )
            kept = [user_msg, asst_msg]
        break
    return kept


def _trim_provider_messages_with_pinned_user(
    messages: list[dict[str, Any]], token_budget: int, pinned_user_index: int
) -> list[dict[str, Any]]:
    """Trim history while retaining the current user turn at all costs.

    Retrieval prefetch replaces the current user turn with one envelope that
    contains both the original question and untrusted evidence. In a tool loop
    there can be newer assistant/tool-result messages, so the generic
    newest-first trimmer is not enough to guarantee that anchor survives.
    """
    if token_budget <= 0 or not (0 <= pinned_user_index < len(messages)):
        return _trim_provider_messages(messages, token_budget)

    pinned = messages[pinned_user_index]
    if pinned.get("role") != "user" or not isinstance(pinned.get("content"), str):
        return _trim_provider_messages(messages, token_budget)

    pinned_cost = _estimate_message_tokens(pinned)
    if pinned_cost > token_budget:
        clipped = dict(pinned)
        clipped["content"] = truncate_text_to_token_budget(
            pinned["content"], max(1, token_budget - 6)
        )
        return [clipped]

    remaining = token_budget - pinned_cost
    before_reversed: list[dict[str, Any]] = []
    for message in reversed(messages[:pinned_user_index]):
        cost = _estimate_message_tokens(message)
        if cost > remaining:
            break
        before_reversed.append(message)
        remaining -= cost

    after = messages[pinned_user_index + 1 :]
    after_cost = sum(_estimate_message_tokens(message) for message in after)
    # Tool results are only valid after their matching assistant tool call.
    # Keep this suffix as one atomic chain; a partial newest-first suffix could
    # otherwise send an orphaned ``tool_result`` to a provider.
    kept_after = after if after_cost <= remaining else []

    # The anchor is a genuine user turn, so trimming older history cannot leave
    # the final provider request without a question to answer. Newer tool-loop
    # blocks stay after it in their original order when the full tool chain fits.
    return list(reversed(before_reversed)) + [pinned] + kept_after


def allocate_provider_context(
    *,
    model: str,
    system_prompt: str,
    tools_schema: list[dict[str, Any]],
    conversation_messages: list[dict[str, Any]],
    configured_context_window: int | None = None,
    output_token_budget: int | None = None,
    pinned_user_index: int | None = None,
) -> list[dict[str, Any]]:
    """Fit actual prompt components into the selected model's context window.

    Fixed reserves are retained as a safety cushion, but the system prompt and
    tool schemas are now measured on every model call. The remaining capacity
    is allocated to the newest complete conversation/tool messages.
    """
    from src.models.tokenizer import token_model_scope

    with token_model_scope(model):
        context_window = context_window_for_model(model, configured_context_window)
        system_tokens = estimate_tokens(system_prompt, model=model)
        tool_tokens = estimate_tokens(
            json.dumps(tools_schema, ensure_ascii=False, default=str), model=model
        )
        output_budget = output_token_budget or MAX_OUTPUT_TOKENS
        conversation_budget = context_window - output_budget - SAFETY_RESERVE
        conversation_budget -= system_tokens + tool_tokens
        # This is a hard physical remainder, not a target.  Keeping a 1K
        # minimum here used to make a small BYOK model overflow whenever the
        # system prompt, tool schemas, or retrieved context already consumed
        # its window.  Callers must instead shrink optional prompt blocks (or
        # reject an impossible model configuration) before reaching this step.
        conversation_budget = max(0, conversation_budget)
        if pinned_user_index is not None:
            return _trim_provider_messages_with_pinned_user(
                conversation_messages, conversation_budget, pinned_user_index
            )
        return _trim_provider_messages(conversation_messages, conversation_budget)


def provider_fixed_prompt_tokens(
    system_prompt: str,
    tools_schema: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> int:
    """Measure the non-history portion of one provider request.

    Kept alongside the final allocator so optional context producers (notably
    RAG) can reserve only what the selected model can actually accept.
    """
    return estimate_tokens(system_prompt, model=model) + estimate_tokens(
        json.dumps(tools_schema, ensure_ascii=False, default=str), model=model
    )


def _prompt_reserve_tokens(system_prompt: str, tools_schema: list[dict[str, Any]]) -> int:
    return (
        estimate_tokens(system_prompt)
        + estimate_tokens(json.dumps(tools_schema, ensure_ascii=False, default=str))
        + 1_000
    )


def _infer_output_task(messages: list[dict[str, Any]], has_retrieval: bool) -> str:
    latest = _latest_user_text(messages).lower()
    report_keywords = (
        "报告",
        "文档",
        "完整",
        "详细",
        "对比",
        "表格",
        "一览",
        "清单",
        "总结",
        "report",
        "table",
        "compare",
        "summary",
    )
    long_keywords = ("区别", "列出", "全部", "所有", "分析", "方案", "步骤", "为什么")
    if any(keyword in latest for keyword in report_keywords):
        return "report"
    if has_retrieval and any(keyword in latest for keyword in long_keywords):
        return "long_answer"
    return "answer"
