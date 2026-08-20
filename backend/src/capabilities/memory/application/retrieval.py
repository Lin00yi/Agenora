"""User-memory retrieval use cases, embedding helpers, and prompt blocks."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.capabilities.conversations.models import UserMemory
from src.platform.llm.tokenizer import count_tokens, truncate_to_token_budget
from src.capabilities.memory.domain.policy import (
    MAX_MEMORY_CONTEXT_TOKENS,
    MEMORY_CONFIDENCE_WEIGHT,
    MEMORY_IMPORTANCE_WEIGHT,
    MEMORY_INJECT_DEDUPE_COSINE,
    MEMORY_RETRIEVAL_LIMIT,
    MEMORY_SEMANTIC_MIN,
    PROFILE_PREFERENCE_KEYS,
)
from src.capabilities.memory.domain.extraction import memory_content_rejection_reason


@dataclass(frozen=True)
class MemoryRetrievalMatch:
    """A selected memory plus a safe explanation of why it matched.

    Scores are diagnostic metadata only. Raw query terms and embeddings stay
    out of the trace, so this object cannot reveal a prompt or vector payload.
    """

    memory: UserMemory
    score: float
    matched_by: tuple[str, ...]

    def trace_metadata(self) -> dict[str, object]:
        return {
            "score": round(self.score, 3),
            "matched_by": list(self.matched_by),
        }


def estimate_tokens(text: str) -> int:
    return count_tokens(text)


def truncate_text_to_token_budget(text: str, token_budget: int, *, suffix: str = "…[已截断]") -> str:
    return truncate_to_token_budget(text, token_budget, suffix=suffix)

def _memory_terms(text: str) -> set[str]:
    lowered = text.lower()
    words = set(re.findall(r"[a-zA-Z0-9_+\-.]{3,}", lowered))
    cjk_chunks = set(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    return words | cjk_chunks


async def retrieve_user_memory_matches(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    kb_id: str | None = None,
    limit: int = MEMORY_RETRIEVAL_LIMIT,
    embedding_cfg=None,
    exclude_ids: set[str] | frozenset[str] | None = None,
) -> list[MemoryRetrievalMatch]:
    """Hybrid retrieval with a safe lexical fallback and traceable matches.

    Memory vectors deliberately live beside the relational rows.  That keeps
    per-user data isolated and portable; with the bounded (50-row) candidate
    set, in-process cosine scoring is cheaper and simpler than provisioning a
    second vector collection per user.
    """
    excluded = exclude_ids or set()
    result = await session.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > datetime.now(timezone.utc)),
        )
        .order_by(desc(UserMemory.updated_at))
        .limit(50)
    )
    rows = [
        row
        for row in result.scalars().all()
        if row.id not in excluded and not memory_content_rejection_reason(row.content or "")
    ]
    if not rows:
        return []

    query_terms = _memory_terms(query)
    query_vector, fingerprint = await _memory_query_vector(query, embedding_cfg)
    if query_vector and fingerprint:
        # Existing installs predate memory vectors. Backfill a small batch on
        # demand; failures remain non-fatal and lexical retrieval still works.
        backfilled = await _backfill_memory_embeddings(
            rows, fingerprint=fingerprint, embedding_cfg=embedding_cfg, max_rows=20
        )
        if backfilled:
            await session.commit()
    wants_preferences = bool(re.search(r"偏好|默认|风格|语言|格式|习惯", query))
    scored: list[tuple[float, UserMemory]] = []
    match_reasons: dict[str, tuple[str, ...]] = {}
    for row in rows:
        if row.scope == "kb" and row.scope_id != kb_id:
            continue
        if row.scope not in {"personal", "kb"}:
            continue
        # Always-on response preferences live in the profile block; skip them
        # here so they do not consume retrieval slots or double-inject.
        if (
            row.scope == "personal"
            and row.type == "preference"
            and row.memory_key in PROFILE_PREFERENCE_KEYS
        ):
            continue
        terms = _memory_terms(row.content)
        keyword_score = len(query_terms & terms)
        semantic_score = 0.0
        vector = _memory_vector(row)
        if query_vector and fingerprint == row.embedding_fingerprint and vector:
            semantic_score = max(0.0, _cosine_similarity(query_vector, vector))
        keyword_hit = keyword_score > 0
        semantic_hit = semantic_score >= MEMORY_SEMANTIC_MIN
        # Preference-seeking queries may boost preference rows, but type_bonus
        # alone must not admit every preference without keyword/semantic signal.
        preference_boost = wants_preferences and row.type == "preference"
        if not (keyword_hit or semantic_hit):
            continue
        type_bonus = 1.5 if preference_boost else 0.0
        scope_bonus = 0.75 if row.scope == "kb" and row.scope_id == kb_id else 0.0
        relevance = (
            keyword_score * 4
            + semantic_score * 5
            + type_bonus
            + scope_bonus
        )
        if relevance <= 0:
            continue
        score = (
            relevance
            + float(row.importance or 0.5) * MEMORY_IMPORTANCE_WEIGHT
            + float(row.confidence or 0.0) * MEMORY_CONFIDENCE_WEIGHT
        )
        scored.append((score, row))
        reasons: list[str] = []
        if keyword_hit:
            reasons.append("keyword")
        if semantic_hit:
            reasons.append("semantic")
        if preference_boost:
            reasons.append("preference_intent")
        if scope_bonus:
            reasons.append("kb_scope")
        match_reasons[row.id] = tuple(reasons or ["query_relevance"])
    scored.sort(key=lambda item: item[0], reverse=True)
    deduped = _dedupe_scored_memories(scored)
    selected_pairs = deduped[:limit]
    selected = [row for _, row in selected_pairs]
    if selected:
        now = datetime.now(timezone.utc)
        for row in selected:
            row.last_accessed_at = now
            row.recall_count = int(row.recall_count or 0) + 1
    return [
        MemoryRetrievalMatch(
            memory=row,
            score=score,
            matched_by=match_reasons.get(row.id, ("query_relevance",)),
        )
        for score, row in selected_pairs
    ]


async def retrieve_user_memories(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    kb_id: str | None = None,
    limit: int = MEMORY_RETRIEVAL_LIMIT,
    embedding_cfg=None,
    exclude_ids: set[str] | frozenset[str] | None = None,
) -> list[UserMemory]:
    """Backward-compatible row-only view for callers without trace needs."""
    matches = await retrieve_user_memory_matches(
        session,
        user_id=user_id,
        query=query,
        kb_id=kb_id,
        limit=limit,
        embedding_cfg=embedding_cfg,
        exclude_ids=exclude_ids,
    )
    return [match.memory for match in matches]


def _dedupe_scored_memories(
    scored: list[tuple[float, UserMemory]],
    *,
    cosine_threshold: float = MEMORY_INJECT_DEDUPE_COSINE,
) -> list[tuple[float, UserMemory]]:
    """Keep the higher-scoring row when near-duplicate explicits both match."""
    kept: list[tuple[float, UserMemory]] = []
    for score, row in scored:
        row_vector = _memory_vector(row)
        duplicate = False
        for _, existing in kept:
            if (
                existing.type != row.type
                or existing.scope != row.scope
                or existing.scope_id != row.scope_id
                or (existing.embedding_fingerprint or "") != (row.embedding_fingerprint or "")
            ):
                continue
            existing_vector = _memory_vector(existing)
            if not row_vector or not existing_vector:
                continue
            if _cosine_similarity(row_vector, existing_vector) >= cosine_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append((score, row))
    return kept


def _memory_vector(row: UserMemory) -> list[float] | None:
    if not row.embedding_json:
        return None
    try:
        value = json.loads(row.embedding_json)
        if not isinstance(value, list) or not value:
            return None
        vector = [float(item) for item in value]
        return vector if all(math.isfinite(item) for item in vector) else None
    except (TypeError, ValueError):
        return None


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left or not right:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


async def _memory_query_vector(query: str, embedding_cfg) -> tuple[list[float] | None, str | None]:
    if not query.strip():
        return None, None
    try:
        from src.platform.vector.embedding import embed, embedding_fingerprint
        if not memory_embedding_is_available(embedding_cfg):
            return None, None

        return await embed(query, cfg=embedding_cfg), embedding_fingerprint(embedding_cfg)
    except Exception:  # noqa: BLE001 - memory retrieval must not break chat
        return None, None


def memory_embedding_is_available(embedding_cfg=None) -> bool:
    """Avoid accidental default-OpenAI requests on an unconfigured install."""
    if embedding_cfg is not None:
        return True
    from src.settings import get_settings

    settings = get_settings()
    return not (
        settings.embedding_provider == "openai"
        and not settings.embedding_base_url
        and not settings.embedding_api_key
        and not settings.openai_api_key
    )


async def _backfill_memory_embeddings(
    rows: Iterable[UserMemory], *, fingerprint: str, embedding_cfg, max_rows: int
) -> bool:
    missing = [
        row for row in rows
        if row.embedding_fingerprint != fingerprint or _memory_vector(row) is None
    ][:max_rows]
    if not missing:
        return False
    try:
        from src.platform.vector.embedding import embed_batch

        vectors = await embed_batch([row.content for row in missing], cfg=embedding_cfg)
        changed = False
        for row, vector in zip(missing, vectors):
            if vector:
                row.embedding_json = json.dumps(vector, separators=(",", ":"))
                row.embedding_fingerprint = fingerprint
                changed = True
        return changed
    except Exception:  # noqa: BLE001 - the lexical path remains available
        return False


async def refresh_memory_embedding(row: UserMemory, *, embedding_cfg=None) -> bool:
    """Refresh one row after capture/edit; returns False without raising on IO errors."""
    try:
        from src.platform.vector.embedding import embed, embedding_fingerprint

        vector = await embed(row.content, cfg=embedding_cfg)
        if not vector:
            return False
        row.embedding_json = json.dumps(vector, separators=(",", ":"))
        row.embedding_fingerprint = embedding_fingerprint(embedding_cfg)
        return True
    except Exception:  # noqa: BLE001
        return False


async def backfill_user_memory_embeddings(
    session: AsyncSession,
    *,
    user_id: str,
    embedding_cfg=None,
    limit: int = 100,
) -> int:
    """Backfill active Memory vectors for one user without failing the job.

    A model/provider change changes the fingerprint, so the row is deliberately
    re-embedded rather than compared across incompatible vector spaces.
    """
    if limit <= 0 or not memory_embedding_is_available(embedding_cfg):
        return 0
    try:
        from src.platform.vector.embedding import embedding_fingerprint

        fingerprint = embedding_fingerprint(embedding_cfg)
        rows = list(
            (
                await session.execute(
                    select(UserMemory)
                    .where(UserMemory.user_id == user_id, UserMemory.status == "active")
                    .order_by(desc(UserMemory.updated_at))
                    .limit(limit)
                )
            ).scalars()
        )
        before = sum(
            row.embedding_fingerprint == fingerprint and _memory_vector(row) is not None
            for row in rows
        )
        await _backfill_memory_embeddings(
            rows, fingerprint=fingerprint, embedding_cfg=embedding_cfg, max_rows=limit
        )
        after = sum(
            row.embedding_fingerprint == fingerprint and _memory_vector(row) is not None
            for row in rows
        )
        return after - before
    except Exception:  # noqa: BLE001 - maintenance must preserve chat availability
        return 0


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
        # The join newline also consumes a token under the conservative
        # estimator. Reserve it before clipping so this remains a hard cap.
        remaining = token_budget - estimate_tokens("\n".join(lines)) - estimate_tokens("\n")
        clipped = truncate_text_to_token_budget(candidate, remaining)
        if clipped:
            lines.append(clipped)
        break
    return "\n".join(lines)
