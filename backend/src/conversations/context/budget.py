"""Token estimation and context budget helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.conversations.models import ConversationSummary, Message

from .constants import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_OUTPUT_TOKENS,
    FORCE_SUMMARY_RATIO,
    MAX_OUTPUT_TOKENS,
    MIN_OUTPUT_TOKENS,
    MODEL_CONTEXT_WINDOWS,
    OUTPUT_TASK_TARGETS,
    OUTPUT_TOKEN_HARD_CAP,
    PREPARE_SUMMARY_RATIO,
    RAG_RESERVE,
    RECENT_TURNS,
    SAFETY_RESERVE,
    SUMMARY_TRIGGER_RATIO,
    SYSTEM_AND_TOOL_RESERVE,
    ContextBudget,
)

def estimate_tokens(text: str, *, model: str | None = None) -> int:
    """Count tokens for context budgeting.

    Prefers tiktoken (see ``src.infra.tokenizer``). Falls back to a CJK-aware
    heuristic when the tokenizer package is unavailable.
    """
    from src.infra.tokenizer import count_tokens

    return count_tokens(text, model=model)


def estimate_messages_tokens(
    messages: list[Message] | list[dict[str, str]],
    *,
    model: str | None = None,
) -> int:
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg, Message) else msg.get("content", "")
        total += estimate_tokens(content, model=model) + 6
    return total


def truncate_text_to_token_budget(
    text: str,
    token_budget: int,
    *,
    suffix: str = "…[已截断]",
    model: str | None = None,
) -> str:
    """Return a prefix that fits ``token_budget`` under the active tokenizer."""
    from src.infra.tokenizer import truncate_to_token_budget

    return truncate_to_token_budget(text, token_budget, suffix=suffix, model=model)


def trim_messages_to_token_budget(
    messages: list[Message], token_budget: int
) -> list[Message]:
    """Keep the newest complete messages within a concrete context budget."""
    if token_budget <= 0:
        return []

    kept_reversed: list[Message] = []
    remaining = token_budget
    for message in reversed(messages):
        cost = estimate_tokens(message.content or "") + 6
        if cost <= remaining:
            kept_reversed.append(message)
            remaining -= cost
            continue
        # The newest message is always more valuable than older context. Keep
        # a bounded copy even when one message alone is over budget.
        if not kept_reversed:
            clipped = Message(
                id=message.id,
                conversation_id=message.conversation_id,
                role=message.role,
                content=truncate_text_to_token_budget(message.content or "", max(1, remaining - 6)),
            )
            kept_reversed.append(clipped)
        break

    kept = list(reversed(kept_reversed))
    # A standalone assistant reply has no preceding user turn and is less
    # useful than the retained recent turns. Prefer recovering the prior user
    # turn (clipped) over returning an empty history.
    while kept and kept[0].role == "assistant":
        if len(kept) > 1:
            kept.pop(0)
            continue
        orphan = kept[0]
        orphan_index = next((i for i, item in enumerate(messages) if item.id == orphan.id), -1)
        prior = messages[orphan_index - 1] if orphan_index > 0 else None
        if prior is None or prior.role != "user":
            break
        assistant_cost = estimate_tokens(orphan.content or "") + 6
        if assistant_cost + 40 <= token_budget:
            user_room = max(1, token_budget - assistant_cost - 6)
            user_text = truncate_text_to_token_budget(prior.content or "", user_room)
            kept = [
                Message(
                    id=prior.id,
                    conversation_id=prior.conversation_id,
                    role="user",
                    content=user_text,
                ),
                orphan,
            ]
        else:
            user_cap = max(1, token_budget // 2 - 6)
            user_text = truncate_text_to_token_budget(prior.content or "", user_cap)
            used = estimate_tokens(user_text) + 6
            asst_text = truncate_text_to_token_budget(
                orphan.content or "", max(1, token_budget - used - 6)
            )
            kept = [
                Message(
                    id=prior.id,
                    conversation_id=prior.conversation_id,
                    role="user",
                    content=user_text,
                ),
                Message(
                    id=orphan.id,
                    conversation_id=orphan.conversation_id,
                    role="assistant",
                    content=asst_text,
                ),
            ]
        break
    return kept


ContextWindowSource = Literal["manual", "registry", "fallback"]


@dataclass(frozen=True)
class ContextWindowResolution:
    """The effective context capacity and why it was selected."""

    value: int
    source: ContextWindowSource


def resolve_context_window(
    model: str | None, configured_window: int | None = None
) -> ContextWindowResolution:
    """Resolve a model's usable input window from one server-owned registry.

    A stored value is an intentional BYOK override. Unknown OpenAI-compatible
    models fall back conservatively rather than assuming the capacity of a
    similarly named public model.
    """
    if configured_window is not None:
        return ContextWindowResolution(configured_window, "manual")
    if not model:
        return ContextWindowResolution(DEFAULT_CONTEXT_WINDOW, "fallback")
    configured = MODEL_CONTEXT_WINDOWS.get(model)
    if configured:
        return ContextWindowResolution(configured, "registry")
    normalized = model.lower()
    if normalized.startswith(("gpt-3.5", "gpt-4-0613", "gpt-4-32k")):
        return ContextWindowResolution(16_000, "registry")
    return ContextWindowResolution(DEFAULT_CONTEXT_WINDOW, "fallback")


def context_window_for_model(model: str | None, configured_window: int | None = None) -> int:
    """Compatibility helper for call sites that only need the numeric budget."""
    return resolve_context_window(model, configured_window).value


OutputTask = Literal["answer", "long_answer", "report"]


def resolve_output_token_budget(
    *,
    model: str | None,
    configured_window: int | None = None,
    task: OutputTask = "answer",
    reserved_prompt_tokens: int = 0,
) -> int:
    """Pick a safe per-call output budget without needing a complete model table.

    Known context windows and BYOK user configuration tell us the total request
    budget. The task decides the desired verbosity; the context window and a
    hard application cap keep unknown OpenAI-compatible models from receiving
    unbounded `max_tokens`.
    """
    window = context_window_for_model(model, configured_window)
    target = OUTPUT_TASK_TARGETS.get(task, DEFAULT_OUTPUT_TOKENS)
    inferred_cap = min(OUTPUT_TOKEN_HARD_CAP, max(DEFAULT_OUTPUT_TOKENS, window // 4))
    max_by_context = window - SAFETY_RESERVE - max(0, reserved_prompt_tokens)
    budget = min(target, inferred_cap, max_by_context)
    return max(MIN_OUTPUT_TOKENS, int(budget))


def rag_reserve_for_kb(kb_id: str | None) -> int:
    """Reserve RAG capacity only when the conversation can inject KB context."""
    return RAG_RESERVE if kb_id else 0


def compute_budget(
    messages: list[Message],
    model: str | None,
    configured_window: int | None = None,
    *,
    rag_reserve: int | None = None,
) -> ContextBudget:
    from src.infra.tokenizer import token_model_scope

    window = context_window_for_model(model, configured_window)
    reserved_rag = RAG_RESERVE if rag_reserve is None else max(0, int(rag_reserve))
    available = max(
        4_000,
        window - MAX_OUTPUT_TOKENS - SYSTEM_AND_TOOL_RESERVE - reserved_rag - SAFETY_RESERVE,
    )
    with token_model_scope(model):
        current = estimate_messages_tokens(messages, model=model)
    ratio = current / available if available else 1.0
    return ContextBudget(
        model=model,
        context_window=window,
        available_history_tokens=available,
        current_history_tokens=current,
        ratio=ratio,
        should_prepare_summary=ratio >= PREPARE_SUMMARY_RATIO,
        should_summarize=ratio >= SUMMARY_TRIGGER_RATIO,
        force_summarize=ratio >= FORCE_SUMMARY_RATIO,
    )


def estimate_effective_context_tokens(
    messages: list[Message],
    summary: ConversationSummary | None,
    *,
    model: str | None = None,
) -> int:
    """Estimate tokens that would enter the prompt after summary compression.

    Raw history can stay large after a rolling summary exists. Status meters
    should reflect the bounded prompt, not the uncompressed archive size.
    """
    from src.infra.tokenizer import token_model_scope

    with token_model_scope(model):
        if not summary:
            return estimate_messages_tokens(messages, model=model)
        keep_count = RECENT_TURNS * 2
        recent = messages[-keep_count:] if messages else []
        summary_tokens = summary.token_count or estimate_tokens(summary.summary or "", model=model)
        return summary_tokens + estimate_messages_tokens(recent, model=model)


def context_status_payload(
    *,
    budget: ContextBudget,
    summary: ConversationSummary | None,
    effective_tokens: int | None = None,
) -> dict:
    measured = (
        budget.current_history_tokens
        if effective_tokens is None
        else max(0, int(effective_tokens))
    )
    display_ratio = (
        measured / budget.available_history_tokens
        if budget.available_history_tokens
        else 1.0
    )
    if summary:
        state = "compressed"
        label = "已压缩"
        description = f"已压缩早期 {summary.covered_message_count} 条消息，保留最近 {RECENT_TURNS} 轮完整对话。"
    elif budget.force_summarize:
        state = "critical"
        label = "即将压缩"
        description = "上下文接近上限，下一次请求会优先压缩早期对话。"
    elif budget.should_summarize:
        state = "ready"
        label = "准备压缩"
        description = "上下文已达到压缩阈值，后续请求会自动整理早期内容。"
    elif budget.should_prepare_summary:
        state = "approaching"
        label = "接近阈值"
        description = "当前会话较长，继续对话后可能自动压缩早期上下文。"
    else:
        state = "normal"
        label = "正常"
        description = "当前上下文无需压缩。"

    return {
        "state": state,
        "label": label,
        "description": description,
        "current_tokens": measured,
        "raw_history_tokens": budget.current_history_tokens,
        "available_tokens": budget.available_history_tokens,
        "context_window": budget.context_window,
        "ratio": round(display_ratio, 4),
        "percent": min(100, round(display_ratio * 100)),
        "prepare_threshold_percent": round(PREPARE_SUMMARY_RATIO * 100),
        "summary_threshold_percent": round(SUMMARY_TRIGGER_RATIO * 100),
        "force_threshold_percent": round(FORCE_SUMMARY_RATIO * 100),
        "summary": summary.to_public_dict() if summary else None,
        "retained_recent_turns": RECENT_TURNS,
    }
