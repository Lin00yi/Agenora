"""Assemble bounded prompt context for a conversation turn."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations.models import Message

from .budget import (
    compute_budget,
    estimate_tokens,
    rag_reserve_for_kb,
    trim_messages_to_token_budget,
    truncate_text_to_token_budget,
)
from .constants import MAX_SUMMARY_CONTEXT_TOKENS, RECENT_TURNS, BuiltContext
from .memory_retrieve import memory_block, retrieve_user_memories
from .memory_store import _memory_trace_item
from .profile import build_user_memory_profile, user_profile_block
from .summary import ensure_summary_if_needed

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig

async def build_context_for_conversation(
    session: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    model: str | None,
    kb_id: str | None = None,
    context_window: int | None = None,
    llm_cfg: "UserLLMConfig | None" = None,
    embedding_cfg=None,
) -> BuiltContext:
    from src.infra.tokenizer import token_model_scope

    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = list(result.scalars().all())
    with token_model_scope(model):
        budget = compute_budget(
            messages,
            model,
            context_window,
            rag_reserve=rag_reserve_for_kb(kb_id),
        )
        summary = await ensure_summary_if_needed(
            session,
            conversation_id=conversation_id,
            messages=messages,
            budget=budget,
            llm_cfg=llm_cfg,
        )

        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        profile = await build_user_memory_profile(session, user_id=user_id, kb_id=kb_id)
        profile_ids = set(profile.get("memory_ids") or set())
        memories = await retrieve_user_memories(
            session,
            user_id=user_id,
            query=last_user.content if last_user else "",
            kb_id=kb_id,
            embedding_cfg=embedding_cfg,
            exclude_ids=profile_ids,
        )

        keep_count = RECENT_TURNS * 2
        out: list[dict[str, str]] = []
        profile_text = user_profile_block(profile)
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
            budget.available_history_tokens
            - estimate_tokens(profile_text)
            - estimate_tokens(mem_text)
            - estimate_tokens(summary_text),
        )
        recent_source = messages[-keep_count:] if summary else messages
        recent = trim_messages_to_token_budget(recent_source, recent_budget)
        if profile_text:
            out.append(
                {"role": "system", "content": profile_text, "_context_source": "profile"}
            )
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
            memory_trace={
                "profile": {
                    "injected": bool(profile_text),
                    "counts": profile.get("counts", {}),
                    "items": profile.get("items", [])[:12],
                },
                "memories": {
                    "injected_count": len(memories),
                    "items": [_memory_trace_item(row) for row in memories],
                },
                "summary": (
                    {
                        "id": summary.id,
                        "covered_message_count": summary.covered_message_count,
                        "token_count": summary.token_count,
                        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
                    }
                    if summary
                    else None
                ),
                "recent_message_count": len(recent),
            },
        )

