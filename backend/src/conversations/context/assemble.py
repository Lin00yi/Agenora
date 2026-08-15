"""Assemble bounded prompt context for a conversation turn."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations.models import Message

from .budget import (
    allocate_context_blocks,
    compute_budget,
    estimate_tokens,
    rag_reserve_for_kb,
    trim_messages_to_token_budget,
    truncate_text_to_token_budget,
)
from .constants import MAX_SUMMARY_CONTEXT_TOKENS, BuiltContext
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

        out: list[dict[str, str]] = []
        profile_text = user_profile_block(profile)
        mem_text = memory_block(memories)
        summary_source = summary.summary if summary else ""
        allocation = allocate_context_blocks(
            budget.available_history_tokens,
            # ``estimate_messages_tokens`` charges the provider message-frame
            # overhead as well. Reserve it here too so the assembled list is a
            # true hard cap rather than three text-only approximations.
            profile_tokens=estimate_tokens(profile_text) + (6 if profile_text else 0),
            memory_tokens=estimate_tokens(mem_text) + (6 if mem_text else 0),
            summary_tokens=min(
                estimate_tokens(summary_source), MAX_SUMMARY_CONTEXT_TOKENS
            ) + (
                6 if summary_source else 0
            ),
        )
        profile_text = (
            truncate_text_to_token_budget(profile_text, allocation.profile - 6)
            if profile_text and allocation.profile > 6
            else ""
        )
        mem_text = (
            truncate_text_to_token_budget(mem_text, allocation.memory - 6)
            if mem_text and allocation.memory > 6
            else ""
        )
        summary_text = (
            truncate_text_to_token_budget(summary_source, allocation.summary - 6)
            if summary_source and allocation.summary > 6
            else ""
        )

        covered_count = min(
            max(0, summary.covered_message_count if summary else 0), len(messages)
        )
        # Keep every turn that has not entered the rolling summary, subject to
        # the selected model's measured budget. This avoids silently losing
        # messages that arrived after an older summary when switching models.
        live_source = messages[covered_count:] if summary else messages
        rehydrated: list[Message] = []
        if summary and allocation.recent:
            live_tokens = 0 if not live_source else sum(
                estimate_tokens(item.content or "") + 6 for item in live_source
            )
            live_budget = min(allocation.recent, live_tokens)
            recent = trim_messages_to_token_budget(live_source, live_budget)
            source_window = summary.source_context_window or 0
            rehydrate_budget = allocation.recent - live_budget
            # When the target window grows, use spare capacity to restore the
            # newest original detail covered by a smaller-window summary. It is
            # deliberately append-only and bounded; the summary remains the
            # stable source for older history.
            if (
                rehydrate_budget > 0
                and source_window > 0
                and budget.context_window > source_window
                and covered_count > 0
            ):
                rehydrated = trim_messages_to_token_budget(
                    messages[:covered_count], rehydrate_budget
                )
        else:
            recent = trim_messages_to_token_budget(live_source, allocation.recent)
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
        out.extend({"role": m.role, "content": m.content or ""} for m in rehydrated)
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
                        "source_model": summary.source_model,
                        "source_context_window": summary.source_context_window,
                        "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
                    }
                    if summary
                    else None
                ),
                "rehydrated_message_count": len(rehydrated),
                "recent_message_count": len(recent),
            },
        )
