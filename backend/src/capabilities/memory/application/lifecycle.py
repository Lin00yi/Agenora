"""Persist, consolidate, and finalize user-memory records."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations.models import Message, UserMemory

from src.context.constants import MEMORY_CONSOLIDATE_SEMANTIC, MemoryCandidate
from src.capabilities.memory.domain.extraction import (
    _constraint_topic_for_candidate,
    constraint_topic_from_memory_key,
    extract_conversation_memory_candidates_with_llm,
    extract_explicit_memory_candidate,
    extract_memory_candidates,
    infer_constraint_topic,
)
from src.capabilities.memory.application.retrieval import (
    _cosine_similarity,
    _memory_vector,
    refresh_memory_embedding,
)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserLLMConfig

def _source_message_ids(row: UserMemory) -> list[str]:
    if not row.source_message_ids:
        return []
    try:
        value = json.loads(row.source_message_ids)
        return [str(item) for item in value] if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def _merge_memory_sources(survivor: UserMemory, redundant: UserMemory) -> None:
    source_ids = list(dict.fromkeys([*_source_message_ids(survivor), *_source_message_ids(redundant)]))
    survivor.source_message_ids = json.dumps(source_ids, ensure_ascii=False)
    survivor.confidence = max(float(survivor.confidence or 0), float(redundant.confidence or 0))
    survivor.importance = max(float(survivor.importance or 0), float(redundant.importance or 0))


def _newer_memory(rows: list[UserMemory]) -> UserMemory:
    return max(rows, key=lambda row: (row.updated_at or row.created_at, row.id))


def _memory_trace_item(row: UserMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "scope": row.scope,
        "scope_id": row.scope_id,
        "type": row.type,
        "key": row.memory_key,
        "content": row.content,
        "source": row.source,
        "confidence": round(float(row.confidence or 0.0), 3),
        "importance": round(float(row.importance or 0.0), 3),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _lock_structured_memory_key(
    session: AsyncSession,
    *,
    user_id: str,
    scope: str,
    scope_id: str | None,
    memory_type: str,
    memory_key: str,
) -> None:
    """Serialize competing structured writes on PostgreSQL.

    The unique partial index remains the final cross-process invariant.  This
    advisory transaction lock turns the usual concurrent preference update
    into deterministic last-writer-wins supersession instead of a retryable
    unique violation. SQLite's single-writer model relies on that same index.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    lock_key = "|".join((user_id, scope, scope_id or "", memory_type, memory_key))
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key}
    )


async def consolidate_user_memories(
    session: AsyncSession,
    *,
    user_id: str,
    semantic_threshold: float = MEMORY_CONSOLIDATE_SEMANTIC,
) -> dict[str, int]:
    """Idempotently expire, de-duplicate and resolve structured conflicts.

    This is intentionally deterministic: we only auto-resolve records that
    share the same structured key, or are near-identical in the same embedding
    space. Ambiguous facts are left untouched rather than silently deleting a
    user's information.
    """
    now = datetime.now(timezone.utc)
    expired_result = await session.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.expires_at.is_not(None),
            UserMemory.expires_at <= now,
        )
    )
    expired = list(expired_result.scalars())
    for row in expired:
        row.status = "expired"
        row.updated_at = now

    result = await session.execute(
        select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.status == "active")
    )
    rows = list(result.scalars())
    superseded = 0
    deduplicated = 0

    # A structured key denotes one current value. This also repairs old data
    # written before the write-path had atomic supersession behaviour.
    keyed: dict[tuple[str, str, str | None, str], list[UserMemory]] = {}
    for row in rows:
        if row.memory_key:
            keyed.setdefault((row.type, row.scope, row.scope_id, row.memory_key), []).append(row)
    for group in keyed.values():
        if len(group) < 2:
            continue
        survivor = _newer_memory(group)
        for row in group:
            if row is survivor:
                continue
            _merge_memory_sources(survivor, row)
            row.status = "superseded"
            if not survivor.supersedes_memory_id:
                survivor.supersedes_memory_id = row.id
            row.updated_at = now
            superseded += 1

    active_rows = [row for row in rows if row.status == "active"]
    # Constraints that share a topic (including legacy hash keys whose content
    # maps to the same topic) keep only the newest active value.
    topic_groups: dict[tuple[str, str | None, str], list[UserMemory]] = {}
    for row in active_rows:
        if row.type != "constraint":
            continue
        topic = constraint_topic_from_memory_key(row.memory_key) or infer_constraint_topic(
            row.memory_key or "",
            row.memory_value or "",
            row.content or "",
        )
        if not topic:
            continue
        # Rewrite legacy / misc keys onto the canonical topic key when we can.
        canonical_key = f"constraint.{topic}"
        if row.memory_key != canonical_key:
            row.memory_key = canonical_key
        topic_groups.setdefault((row.scope, row.scope_id, topic), []).append(row)
    for group in topic_groups.values():
        if len(group) < 2:
            continue
        survivor = _newer_memory(group)
        for row in group:
            if row is survivor:
                continue
            _merge_memory_sources(survivor, row)
            row.status = "superseded"
            if not survivor.supersedes_memory_id:
                survivor.supersedes_memory_id = row.id
            row.updated_at = now
            superseded += 1

    active_rows = [row for row in rows if row.status == "active"]
    # Near-identical free-form/constraint memories frequently acquire distinct
    # misc-hash keys. Merge them only with matching type/scope/fingerprint and a
    # very high cosine threshold to avoid treating related facts as duplicates.
    for index, row in enumerate(active_rows):
        if row.status != "active" or row.type not in {"explicit", "constraint"}:
            continue
        row_vector = _memory_vector(row)
        if not row_vector or not row.embedding_fingerprint:
            continue
        for other in active_rows[index + 1 :]:
            if (
                other.status != "active"
                or other.type != row.type
                or other.scope != row.scope
                or other.scope_id != row.scope_id
                or other.embedding_fingerprint != row.embedding_fingerprint
            ):
                continue
            other_vector = _memory_vector(other)
            if not other_vector or _cosine_similarity(row_vector, other_vector) < semantic_threshold:
                continue
            survivor = _newer_memory([row, other])
            redundant = other if survivor is row else row
            _merge_memory_sources(survivor, redundant)
            redundant.status = "superseded"
            if not survivor.supersedes_memory_id:
                survivor.supersedes_memory_id = redundant.id
            redundant.updated_at = now
            deduplicated += 1
            break

    return {"expired": len(expired), "superseded": superseded, "deduplicated": deduplicated}


async def finalize_memory_rows_heavy(
    session: AsyncSession,
    *,
    user_id: str,
    memory_ids: list[str],
    embedding_cfg=None,
) -> dict[str, int]:
    """Best-effort embedding refresh + consolidate for rows written on the hot path.

    Used by BackgroundTasks after a lightweight ``store_*(..., heavy=False)`` so
    chat append does not wait on the embedding provider.
    """
    ids = [str(item) for item in dict.fromkeys(memory_ids) if item]
    if not ids:
        return {"embedded": 0, "consolidated": 0}
    result = await session.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.id.in_(ids),
        )
    )
    rows = list(result.scalars().all())
    embedded = 0
    for row in rows:
        if await refresh_memory_embedding(row, embedding_cfg=embedding_cfg):
            embedded += 1
    stats = await consolidate_user_memories(session, user_id=user_id)
    return {"embedded": embedded, "consolidated": int(stats.get("deduplicated") or 0)}


async def run_memory_heavy_background(
    user_id: str,
    memory_ids: list[str],
    embedding_cfg=None,
) -> None:
    """Open a fresh session for post-append memory embedding / consolidation."""
    from src.storage.database import get_session_factory

    if not memory_ids:
        return
    factory = get_session_factory()
    try:
        async with factory() as session:
            await finalize_memory_rows_heavy(
                session,
                user_id=user_id,
                memory_ids=memory_ids,
                embedding_cfg=embedding_cfg,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - never fail the chat path via background
        log.exception(
            "memory_heavy_background_failed user_id=%s memory_ids=%s",
            user_id,
            memory_ids,
        )


async def store_memory_candidates(
    session: AsyncSession,
    *,
    user_id: str,
    source_message_ids: list[str],
    candidates: list[MemoryCandidate],
    kb_id: str | None = None,
    embedding_cfg=None,
    heavy: bool = True,
) -> list[UserMemory]:
    """Persist extracted memories through the shared structured write path.

    A new value for the same ``scope + type + key`` automatically supersedes
    the older active row. This prevents conflicting preferences from being
    injected together on later turns.

    When ``heavy=False`` (realtime chat append), only the relational write runs;
    callers should schedule ``run_memory_heavy_background`` after commit.
    """
    stored: list[UserMemory] = []
    source_ids = [str(item) for item in dict.fromkeys(source_message_ids) if item]
    if not source_ids:
        return stored
    unique_candidates = list({candidate.key: candidate for candidate in candidates}.values())
    for candidate in unique_candidates:
        scope = candidate.scope if candidate.scope != "kb" or kb_id else "personal"
        scope_id = kb_id if scope == "kb" else None
        lock_key = candidate.key
        if candidate.type == "constraint":
            topic = _constraint_topic_for_candidate(candidate)
            if topic:
                lock_key = f"constraint.{topic}"
        await _lock_structured_memory_key(
            session,
            user_id=user_id,
            scope=scope,
            scope_id=scope_id,
            memory_type=candidate.type,
            memory_key=lock_key,
        )
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
        # Constraints may still live under a legacy hash key. Match by topic so
        # ``PostgreSQL`` → ``MySQL`` supersedes even before consolidation runs.
        topic_conflicts: list[UserMemory] = []
        if candidate.type == "constraint" and existing is None:
            topic = _constraint_topic_for_candidate(candidate)
            if topic:
                siblings = list(
                    (
                        await session.execute(
                            select(UserMemory).where(
                                UserMemory.user_id == user_id,
                                UserMemory.scope == scope,
                                UserMemory.scope_id == scope_id,
                                UserMemory.type == "constraint",
                                UserMemory.status == "active",
                            )
                        )
                    ).scalars()
                )
                for row in siblings:
                    row_topic = constraint_topic_from_memory_key(row.memory_key) or infer_constraint_topic(
                        row.memory_key or "",
                        row.memory_value or "",
                        row.content or "",
                    )
                    if row_topic == topic:
                        topic_conflicts.append(row)
                if topic_conflicts:
                    existing = _newer_memory(topic_conflicts)

        if existing and existing.memory_value == candidate.value:
            ids = _source_message_ids(existing)
            ids = list(dict.fromkeys([*ids, *source_ids]))
            existing.source_message_ids = json.dumps(ids, ensure_ascii=False)
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.importance = max(existing.importance, candidate.importance)
            existing.memory_key = candidate.key
            existing.content = candidate.content
            if candidate.expires_in_days is not None:
                existing.expires_at = datetime.now(timezone.utc) + timedelta(
                    days=candidate.expires_in_days
                )
            existing.updated_at = datetime.now(timezone.utc)
            for row in topic_conflicts:
                if row is existing:
                    continue
                row.status = "superseded"
                row.updated_at = datetime.now(timezone.utc)
            stored.append(existing)
            continue

        if existing:
            existing.status = "superseded"
            existing.updated_at = datetime.now(timezone.utc)
        for row in topic_conflicts:
            if row is existing:
                continue
            row.status = "superseded"
            row.updated_at = datetime.now(timezone.utc)

        row = UserMemory(
            id=str(uuid.uuid4()),
            user_id=user_id,
            scope=scope,
            scope_id=scope_id,
            type=candidate.type,
            memory_key=candidate.key,
            memory_value=candidate.value,
            content=candidate.content,
            source_message_ids=json.dumps(source_ids, ensure_ascii=False),
            source=candidate.source,
            confidence=candidate.confidence,
            importance=candidate.importance,
            status="active",
            supersedes_memory_id=existing.id if existing else None,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(days=candidate.expires_in_days)
                if candidate.expires_in_days is not None
                else None
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(row)
        stored.append(row)
    if stored:
        # Flush gives newly captured rows primary identity in the same request;
        # embedding is best-effort, never a reason to reject a chat message.
        await session.flush()
        if heavy:
            for row in stored:
                await refresh_memory_embedding(row, embedding_cfg=embedding_cfg)
            await consolidate_user_memories(session, user_id=user_id)
    return stored


async def store_user_memories(
    session: AsyncSession,
    *,
    user_id: str,
    message_id: str,
    content: str,
    kb_id: str | None = None,
    embedding_cfg=None,
    heavy: bool = True,
) -> list[UserMemory]:
    """Persist high-confidence explicit or implicit memories without UI friction."""
    return await store_memory_candidates(
        session,
        user_id=user_id,
        source_message_ids=[message_id],
        candidates=extract_memory_candidates(content),
        kb_id=kb_id,
        embedding_cfg=embedding_cfg,
        heavy=heavy,
    )


async def extract_conversation_memories(
    session: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    kb_id: str | None = None,
    llm_cfg: "UserLLMConfig | None" = None,
    embedding_cfg=None,
) -> dict[str, int]:
    """Run the lower-frequency whole-conversation memory extraction pass."""
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = list(result.scalars().all())
    user_messages = [message for message in messages if message.role == "user" and message.content]
    if not user_messages:
        return {"messages_scanned": 0, "rule_candidates": 0, "llm_candidates": 0, "stored": 0}

    stored_by_id: dict[str, UserMemory] = {}
    rule_candidate_count = 0
    for message in user_messages:
        candidates = extract_memory_candidates(message.content or "")
        rule_candidate_count += len(candidates)
        rows = await store_memory_candidates(
            session,
            user_id=user_id,
            source_message_ids=[message.id],
            candidates=candidates,
            kb_id=kb_id,
            embedding_cfg=embedding_cfg,
        )
        for row in rows:
            stored_by_id[row.id] = row

    llm_candidates = await extract_conversation_memory_candidates_with_llm(
        messages, llm_cfg=llm_cfg
    )
    rows = await store_memory_candidates(
        session,
        user_id=user_id,
        source_message_ids=[message.id for message in user_messages],
        candidates=llm_candidates,
        kb_id=kb_id,
        embedding_cfg=embedding_cfg,
    )
    for row in rows:
        stored_by_id[row.id] = row

    return {
        "messages_scanned": len(user_messages),
        "rule_candidates": rule_candidate_count,
        "llm_candidates": len(llm_candidates),
        "stored": len(stored_by_id),
    }


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
