"""Conversation context assembly for long-running chats.

The database message rows remain the source of truth. This module builds the
bounded prompt context used by `/api/chat` and stores compact summaries when a
conversation grows beyond the configured budget.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

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
MAX_MEMORY_CONTEXT_TOKENS = 1_200
MAX_SUMMARY_CONTEXT_TOKENS = 2_600
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


@dataclass(frozen=True)
class MemoryCandidate:
    """A high-confidence memory inferred from one user-authored message."""

    type: str
    key: str
    value: str
    content: str
    confidence: float
    importance: float
    source: str
    scope: str = "personal"


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


def truncate_text_to_token_budget(text: str, token_budget: int, *, suffix: str = "…[已截断]") -> str:
    """Return a prefix that fits the cheap multilingual token estimate.

    This is a hard guard around individual context blocks. The estimator is
    deliberately conservative, so a later tokenizer-specific implementation
    can replace it without changing the allocation policy.
    """
    if token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text
    suffix_tokens = estimate_tokens(suffix)
    if suffix_tokens >= token_budget:
        return ""

    low, high = 0, len(text)
    target = token_budget - suffix_tokens
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= target:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + suffix


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
    # useful than the retained recent turns. Remove it for provider-safe chat
    # history (Anthropic requires a user message first).
    while kept and kept[0].role == "assistant":
        kept.pop(0)
    return kept


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
    kb_id: str | None = None,
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
    wants_preferences = bool(re.search(r"偏好|默认|风格|语言|格式|习惯", query))
    scored: list[tuple[float, UserMemory]] = []
    for row in rows:
        if row.scope == "kb" and row.scope_id != kb_id:
            continue
        if row.scope not in {"personal", "kb"}:
            continue
        terms = _memory_terms(row.content)
        keyword_score = len(query_terms & terms)
        type_bonus = 1.5 if wants_preferences and row.type == "preference" else 0.0
        scope_bonus = 0.75 if row.scope == "kb" and row.scope_id == kb_id else 0.0
        if keyword_score > 0 or type_bonus > 0:
            score = (
                keyword_score * 4
                + type_bonus
                + scope_bonus
                + float(row.importance or 0.5)
                + float(row.confidence or 0.0)
            )
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def memory_block(memories: list[UserMemory], *, token_budget: int = MAX_MEMORY_CONTEXT_TOKENS) -> str:
    if not memories:
        return ""
    lines = [
        "以下是用户长期记忆。仅在与当前问题相关时使用，不要透露为系统内部信息："
    ]
    for mem in memories:
        candidate = f"- [{mem.type}] {mem.content}"
        joined = "\n".join([*lines, candidate])
        if estimate_tokens(joined) <= token_budget:
            lines.append(candidate)
            continue
        # Preserve the highest-ranked memory currently being considered, but
        # never let it consume the whole prompt allocation.
        remaining = token_budget - estimate_tokens("\n".join(lines))
        clipped = truncate_text_to_token_budget(candidate, remaining)
        if clipped:
            lines.append(clipped)
        break
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


def _is_question(text: str) -> bool:
    return text.rstrip().endswith(("?", "？", "吗", "么")) or bool(
        re.search(r"能否|可不可以|是否|怎么", text)
    )


def _stable_key(prefix: str, value: str) -> str:
    digest = sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _language_value(value: str) -> str:
    normalized = value.lower()
    if normalized in {"中文", "汉语", "chinese"}:
        return "zh-CN"
    return "en"


def extract_memory_candidates(text: str) -> list[MemoryCandidate]:
    """Silently extract only stable, user-authored, high-confidence memories.

    The rules intentionally favour precision over recall: a false positive is
    more harmful than asking a user to repeat a preference once. Explicit
    ``记住`` commands always qualify; implicit capture requires future/default
    language that signals a durable preference or constraint.
    """
    cleaned = " ".join((text or "").strip().split())
    if not cleaned or contains_sensitive_memory_content(cleaned):
        return []

    explicit = extract_explicit_memory_candidate(cleaned)
    if explicit:
        return [
            MemoryCandidate(
                type="explicit",
                key=_stable_key("explicit", explicit),
                value=explicit,
                content=explicit,
                confidence=0.95,
                importance=0.8,
                source="explicit",
            )
        ]
    if _is_question(cleaned):
        return []

    candidates: list[MemoryCandidate] = []
    future_marker = r"(?:以后|今后|之后|默认|长期|一直)"

    language = re.search(
        future_marker + r".{0,20}?(?:使用|用|回复|回答|输出|写)(中文|汉语|英文|English|Chinese)",
        cleaned,
        re.IGNORECASE,
    )
    if language:
        value = _language_value(language.group(1))
        display = "中文" if value == "zh-CN" else "英文"
        candidates.append(
            MemoryCandidate(
                type="preference",
                key="response_language",
                value=value,
                content=f"用户偏好使用{display}回复。",
                confidence=0.86,
                importance=0.9,
                source="auto_rule",
            )
        )

    style = re.search(
        future_marker + r".{0,24}?(简洁|详细|专业|口语化)(?:回复|回答|输出|报告|说明)?",
        cleaned,
    )
    if style:
        value = style.group(1)
        candidates.append(
            MemoryCandidate(
                type="preference",
                key="response_style",
                value=value,
                content=f"用户偏好{value}的回复风格。",
                confidence=0.82,
                importance=0.75,
                source="auto_rule",
            )
        )

    length = re.search(
        future_marker + r".{0,30}?(?:控制在|不超过|少于)\s*(\d{2,5})\s*字", cleaned
    )
    if length:
        value = length.group(1)
        candidates.append(
            MemoryCandidate(
                type="preference",
                key="response_max_chars",
                value=value,
                content=f"用户偏好回复控制在 {value} 字以内。",
                confidence=0.84,
                importance=0.75,
                source="auto_rule",
            )
        )

    constraint = re.search(
        r"(?:项目|团队|代码库).{0,36}?(必须|禁止|不可|不能|统一使用)\s*(.{4,160})", cleaned
    )
    if constraint:
        value = f"{constraint.group(1)} {constraint.group(2).rstrip('。.!！')}"
        candidates.append(
            MemoryCandidate(
                type="constraint",
                key=_stable_key("constraint", value),
                value=value,
                content=f"项目约束：{value}。",
                confidence=0.8,
                importance=0.9,
                source="auto_rule",
                scope="kb",
            )
        )

    # A message can state the same preference twice; retain one candidate per
    # structured key so writes are deterministic.
    unique: dict[str, MemoryCandidate] = {}
    for candidate in candidates:
        unique[candidate.key] = candidate
    return list(unique.values())


def _source_message_ids(row: UserMemory) -> list[str]:
    if not row.source_message_ids:
        return []
    try:
        value = json.loads(row.source_message_ids)
        return [str(item) for item in value] if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


async def store_user_memories(
    session: AsyncSession,
    *,
    user_id: str,
    message_id: str,
    content: str,
    kb_id: str | None = None,
) -> list[UserMemory]:
    """Persist high-confidence explicit or implicit memories without UI friction.

    A new value for the same ``scope + type + key`` automatically supersedes
    the older active row. This prevents conflicting preferences from being
    injected together on later turns.
    """
    stored: list[UserMemory] = []
    for candidate in extract_memory_candidates(content):
        scope = candidate.scope if candidate.scope != "kb" or kb_id else "personal"
        scope_id = kb_id if scope == "kb" else None
        result = await session.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.scope == scope,
                UserMemory.scope_id == scope_id,
                UserMemory.type == candidate.type,
                UserMemory.memory_key == candidate.key,
                UserMemory.status == "active",
            )
        )
        existing = result.scalar_one_or_none()
        if existing and existing.memory_value == candidate.value:
            ids = _source_message_ids(existing)
            if message_id not in ids:
                ids.append(message_id)
            existing.source_message_ids = json.dumps(ids, ensure_ascii=False)
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.importance = max(existing.importance, candidate.importance)
            existing.updated_at = datetime.now(timezone.utc)
            stored.append(existing)
            continue

        if existing:
            existing.status = "superseded"
            existing.updated_at = datetime.now(timezone.utc)

        row = UserMemory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            scope=scope,
            scope_id=scope_id,
            type=candidate.type,
            memory_key=candidate.key,
            memory_value=candidate.value,
            content=candidate.content,
            source_message_ids=json.dumps([message_id], ensure_ascii=False),
            source=candidate.source,
            confidence=candidate.confidence,
            importance=candidate.importance,
            status="active",
            supersedes_memory_id=existing.id if existing else None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(row)
        stored.append(row)
    return stored


async def store_explicit_user_memory(
    session: AsyncSession,
    *,
    user_id: str,
    message_id: str,
    content: str,
) -> UserMemory | None:
    """Backward-compatible explicit-only entrypoint used by older callers."""
    explicit = extract_explicit_memory_candidate(content)
    if not explicit:
        return None
    rows = await store_user_memories(
        session, user_id=user_id, message_id=message_id, content=content
    )
    return rows[0] if rows else None


async def build_context_for_conversation(
    session: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    model: str | None,
    kb_id: str | None = None,
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
        session, user_id=user_id, query=last_user.content if last_user else "", kb_id=kb_id
    )

    keep_count = RECENT_TURNS * 2
    out: list[dict[str, str]] = []
    mem_text = memory_block(memories)
    summary_text = (
        truncate_text_to_token_budget(summary.summary, MAX_SUMMARY_CONTEXT_TOKENS)
        if summary
        else ""
    )
    # The history budget already leaves room for the system prompt, tool
    # schemas, RAG results and safety margin. Memory and summary now consume
    # a measured portion of that history budget instead of being unbounded.
    recent_budget = max(
        1_000,
        budget.available_history_tokens - estimate_tokens(mem_text) - estimate_tokens(summary_text),
    )
    recent_source = messages[-keep_count:] if summary else messages
    recent = trim_messages_to_token_budget(recent_source, recent_budget)
    if mem_text:
        out.append(
            {"role": "system", "content": mem_text, "_context_source": "memory"}
        )
    if summary_text:
        out.append(
            {"role": "system", "content": summary_text, "_context_source": "summary"}
        )
    out.extend({"role": m.role, "content": m.content or ""} for m in recent)

    return BuiltContext(
        messages=out,
        budget=budget,
        summary=summary,
        injected_memory_count=len(memories),
    )
