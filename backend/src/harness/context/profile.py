"""Always-on user preference profile for prompt injection."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.capabilities.conversations.models import UserMemory

from src.capabilities.memory.application.lifecycle import _memory_trace_item

from .constants import MAX_PROFILE_CONTEXT_TOKENS, MAX_PROFILE_MEMORY_ROWS, PROFILE_PREFERENCE_KEYS
from .token_budget import truncate_text_to_token_budget

async def build_user_memory_profile(
    session: AsyncSession,
    *,
    user_id: str,
    kb_id: str | None = None,
    limit: int = MAX_PROFILE_MEMORY_ROWS,
) -> dict[str, Any]:
    """Build the always-on preference profile for every turn.

    Only stable response preferences belong here. Query-relevant constraints and
    facts are injected separately via ``retrieve_user_memories`` so the same
    row is not double-counted in the prompt budget. ``kb_id`` is accepted for
    call-site symmetry but unused: profile prefs are always personal.
    """
    _ = kb_id
    result = await session.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.scope == "personal",
            UserMemory.type == "preference",
            UserMemory.memory_key.in_(tuple(PROFILE_PREFERENCE_KEYS)),
            or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > datetime.now(timezone.utc)),
        )
        .order_by(desc(UserMemory.importance), desc(UserMemory.updated_at))
        .limit(limit)
    )
    # One row per preference key; importance ordering already applied.
    preferences: list[UserMemory] = []
    seen_keys: set[str] = set()
    for row in result.scalars().all():
        key = row.memory_key or ""
        if key in seen_keys:
            continue
        seen_keys.add(key)
        preferences.append(row)
        if len(preferences) >= len(PROFILE_PREFERENCE_KEYS):
            break

    lines = [f"- 偏好：{row.content}" for row in preferences]

    return {
        "lines": lines,
        "counts": {
            "preferences": len(preferences),
            "constraints": 0,
            "facts": 0,
            "total": len(preferences),
        },
        "items": [_memory_trace_item(row) for row in preferences],
        "memory_ids": {row.id for row in preferences},
    }


def user_profile_block(profile: dict[str, Any], *, token_budget: int = MAX_PROFILE_CONTEXT_TOKENS) -> str:
    lines = list(profile.get("lines") or [])
    if not lines:
        return ""
    block_lines = [
        "以下是来自长期记忆的稳定用户偏好。仅在相关时使用，不要透露为系统内部信息。",
        *lines,
    ]
    return truncate_text_to_token_budget("\n".join(block_lines), token_budget)
