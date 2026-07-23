"""Conversation context assembly for long-running chats.

The database message rows remain the source of truth. This module builds the
bounded prompt context used by `/api/chat` and stores compact summaries when a
conversation grows beyond the configured budget.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations.models import ConversationSummary, Message, UserMemory


MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-7": 200_000,
}

DEFAULT_CONTEXT_WINDOW = 64_000
MAX_OUTPUT_TOKENS = 2_048
SYSTEM_AND_TOOL_RESERVE = 6_000
RAG_RESERVE = 8_000
SAFETY_RESERVE = 2_000
PREPARE_SUMMARY_RATIO = 0.60
SUMMARY_TRIGGER_RATIO = 0.72
FORCE_SUMMARY_RATIO = 0.85
RECENT_TURNS = 10

SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"\b\d{15,18}[\dXx]\b"),
    re.compile(r"\b\d{13,19}\b"),
]


@dataclass
class ContextBudget:
    model: str | None
    context_window: int
    available_history_tokens: int
    current_history_tokens: int
    ratio: float
    should_prepare_summary: bool
    should_summarize: bool
    force_summarize: bool


@dataclass
class BuiltContext:
    messages: list[dict[str, str]]
    budget: ContextBudget
    summary: ConversationSummary | None
    injected_memory_count: int


def estimate_tokens(text: str) -> int:
    """Cheap multilingual token estimate.

    This intentionally overestimates a bit to reduce overflow risk before a
    tokenizer-specific counter is added.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = max(len(text) - cjk, 0)
    return max(1, int(cjk * 1.2 + other / 3.2))


def estimate_messages_tokens(messages: list[Message] | list[dict[str, str]]) -> int:
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg, Message) else msg.get("content", "")
        total += estimate_tokens(content) + 6
    return total


def context_window_for_model(model: str | None) -> int:
    if not model:
        return DEFAULT_CONTEXT_WINDOW
    return MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)


def compute_budget(messages: list[Message], model: str | None) -> ContextBudget:
    window = context_window_for_model(model)
    available = max(
        4_000,
        window - MAX_OUTPUT_TOKENS - SYSTEM_AND_TOOL_RESERVE - RAG_RESERVE - SAFETY_RESERVE,
    )
    current = estimate_messages_tokens(messages)
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


def context_status_payload(
    *,
    budget: ContextBudget,
    summary: ConversationSummary | None,
) -> dict:
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
        "current_tokens": budget.current_history_tokens,
        "available_tokens": budget.available_history_tokens,
        "context_window": budget.context_window,
        "ratio": round(budget.ratio, 4),
        "percent": min(100, round(budget.ratio * 100)),
        "prepare_threshold_percent": round(PREPARE_SUMMARY_RATIO * 100),
        "summary_threshold_percent": round(SUMMARY_TRIGGER_RATIO * 100),
        "force_threshold_percent": round(FORCE_SUMMARY_RATIO * 100),
        "summary": summary.to_public_dict() if summary else None,
        "retained_recent_turns": RECENT_TURNS,
    }


def _message_label(msg: Message) -> str:
    return "用户" if msg.role == "user" else "助手"


def build_extractive_summary(messages: list[Message], max_chars: int = 3600) -> str:
    """Deterministic fallback summarizer.

    It keeps a compact chronological digest without inventing facts. A later
    LLM summarizer can replace this function behind the same interface.
    """
    parts: list[str] = []
    for msg in messages:
        text = " ".join((msg.content or "").split())
        if not text:
            continue
        if len(text) > 280:
            text = text[:277] + "..."
        parts.append(f"- {_message_label(msg)}：{text}")

    body = "\n".join(parts)
    if len(body) > max_chars:
        body = body[-max_chars:]
        first_line = body.find("\n")
        if first_line > 0:
            body = body[first_line + 1 :]
    return "以下是本会话较早内容的压缩摘要，仅用于保持上下文连续性：\n" + body


async def get_latest_summary(
    session: AsyncSession, conversation_id: str
) -> ConversationSummary | None:
    result = await session.execute(
        select(ConversationSummary)
        .where(ConversationSummary.conversation_id == conversation_id)
        .order_by(desc(ConversationSummary.updated_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def ensure_summary_if_needed(
    session: AsyncSession,
    *,
    conversation_id: str,
    messages: list[Message],
    budget: ContextBudget,
) -> ConversationSummary | None:
    summary = await get_latest_summary(session, conversation_id)
    if not budget.should_summarize:
        return summary

    keep_count = RECENT_TURNS * 2
    older = messages[:-keep_count] if len(messages) > keep_count else []
    if len(older) < 4:
        return summary

    covered = older[-1]
    if summary and summary.covered_message_id == covered.id:
        return summary

    text = build_extractive_summary(older)
    row = ConversationSummary(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        summary=text,
        covered_message_id=covered.id,
        covered_message_count=len(older),
        token_count=estimate_tokens(text),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.commit()
    return row


def _memory_terms(text: str) -> set[str]:
    lowered = text.lower()
    words = set(re.findall(r"[a-zA-Z0-9_+\-.]{3,}", lowered))
    cjk_chunks = set(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    return words | cjk_chunks


async def retrieve_user_memories(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    limit: int = 6,
) -> list[UserMemory]:
    result = await session.execute(
        select(UserMemory)
        .where(UserMemory.user_id == user_id, UserMemory.status == "active")
        .order_by(desc(UserMemory.updated_at))
        .limit(50)
    )
    rows = list(result.scalars().all())
    if not rows:
        return []

    query_terms = _memory_terms(query)
    scored: list[tuple[int, UserMemory]] = []
    for row in rows:
        terms = _memory_terms(row.content)
        score = len(query_terms & terms)
        if score > 0 or row.type == "preference":
            scored.append((score, row))
    scored.sort(key=lambda item: (item[0], item[1].confidence), reverse=True)
    return [row for _, row in scored[:limit]]


def memory_block(memories: list[UserMemory]) -> str:
    if not memories:
        return ""
    lines = [
        "以下是用户长期记忆。仅在与当前问题相关时使用，不要透露为系统内部信息："
    ]
    for mem in memories:
        lines.append(f"- [{mem.type}] {mem.content}")
    return "\n".join(lines)


def contains_sensitive_memory_content(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)


def extract_explicit_memory_candidate(text: str) -> str | None:
    """Extract only user-explicit memory requests.

    This avoids silently persisting arbitrary conversation facts. Richer
    candidate extraction can be added later behind user-visible controls.
    """
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return None

    patterns = [
        r"^(?:请你?|帮我)?记住[:：\s]*(.+)$",
        r"^以后(?:请)?记住[:：\s]*(.+)$",
        r"^请把(?:这点|这个|以下内容)?记到长期记忆[:：\s]*(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned)
        if match:
            candidate = match.group(1).strip()
            if 4 <= len(candidate) <= 500 and not contains_sensitive_memory_content(candidate):
                return candidate
    return None


async def store_explicit_user_memory(
    session: AsyncSession,
    *,
    user_id: str,
    message_id: str,
    content: str,
) -> UserMemory | None:
    candidate = extract_explicit_memory_candidate(content)
    if not candidate:
        return None

    existing = await session.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.content == candidate,
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        row.confidence = max(row.confidence, 0.95)
        row.updated_at = datetime.now(timezone.utc)
        return row

    row = UserMemory(
        id=str(uuid.uuid4()),
        user_id=user_id,
        scope="personal",
        type="explicit",
        content=candidate,
        source_message_ids=f'["{message_id}"]',
        confidence=0.95,
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(row)
    return row


async def build_context_for_conversation(
    session: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    model: str | None,
) -> BuiltContext:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = list(result.scalars().all())
    budget = compute_budget(messages, model)
    summary = await ensure_summary_if_needed(
        session,
        conversation_id=conversation_id,
        messages=messages,
        budget=budget,
    )

    last_user = next((m for m in reversed(messages) if m.role == "user"), None)
    memories = await retrieve_user_memories(
        session, user_id=user_id, query=last_user.content if last_user else ""
    )

    keep_count = RECENT_TURNS * 2
    recent = messages[-keep_count:] if summary else messages
    out: list[dict[str, str]] = []
    mem_text = memory_block(memories)
    if mem_text:
        out.append(
            {"role": "system", "content": mem_text, "_context_source": "memory"}
        )
    if summary:
        out.append(
            {"role": "system", "content": summary.summary, "_context_source": "summary"}
        )
    out.extend({"role": m.role, "content": m.content or ""} for m in recent)

    return BuiltContext(
        messages=out,
        budget=budget,
        summary=summary,
        injected_memory_count=len(memories),
    )
