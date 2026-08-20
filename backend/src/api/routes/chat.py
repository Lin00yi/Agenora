"""POST /api/chat — conversation load, BYOK gate, then SSE session."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.api.schemas.chat import ChatRequest
from src.api.streaming.session import run_chat_session
from src.auth.middleware import CurrentUser
from src.context import build_context_for_conversation
from src.conversations.models import Conversation
from src.infra import generation_lock
from src.adapters.persistence import get_session
from src.adapters.llm import normalize_model_name
from src.kb.models import KB
from src.kb.auto_routing import list_readable_routable_kbs
from src.adapters.observability import start_trace
from src.settings import get_settings
from src.settings_user import (
    configured_context_window_for_model,
    list_llm_model_profiles,
    require_user_embedding,
    require_user_llm,
    resolve_llm_profile_config,
    resolve_system_llm,
    resolve_user_embedding,
    resolve_user_llm,
    resolve_user_llm_routing_configs,
    with_model_profile_context,
)

router = APIRouter(tags=["chat"])


@router.post("/api/chat")
async def chat_post(
    req: ChatRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    """SSE stream with full message history. Requires Bearer JWT.

    If kb_id is set, validates ownership and runs the agent in KB-bound mode.

    BYOK gate (v2-M2): when settings.byok_required is True, user must have
    configured their own LLM cfg; if kb_id is set they also need embedding cfg
    (KB-mode chat embeds the query for similarity search).
    """
    conv: Conversation | None = None
    conversation_lock_id: str | None = None
    if req.conversation_id:
        conv = await session.get(Conversation, req.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="conversation not found")
        conversation_lock_id = str(conv.id)
        if not await generation_lock.try_acquire(conversation_lock_id):
            raise HTTPException(
                status_code=409,
                detail="generation_in_progress",
            )

    try:
        # A persisted binding is authoritative. An unbound conversation may be
        # bound by an explicit client choice. For automatic routing this
        # endpoint only prepares ACL-scoped candidates; the Planner/Supervisor
        # DAG owns semantic selection and agent delegation.
        effective_kb_id = conv.kb_id if conv and conv.kb_id else req.kb_id
        route_candidates: list[KB] = []
        selected_profile_id = req.model_profile_id or (conv.llm_profile_id if conv else None)
        selected_model = normalize_model_name(req.model or (conv.llm_model if conv else None))
        base_llm_cfg = (resolve_user_llm(user) if user is not None else None) or resolve_system_llm()
        routing_cfgs = await resolve_user_llm_routing_configs(session, user)
        selected_profile_cfg = await resolve_llm_profile_config(
            session, user=user, profile_id=selected_profile_id
        )
        # BYOK accepts either a legacy config or a selected, independently
        # credentialed model profile.  The former synchronous gate cannot
        # validate profile ownership/health, so run it only after resolution.
        if (
            get_settings().byok_required
            and selected_profile_cfg is None
            and routing_cfgs is None
            and resolve_user_llm(user) is None
        ):
            require_user_llm(user)
        if selected_profile_id and selected_profile_cfg is None:
            raise HTTPException(status_code=422, detail="所选模型档案不可用，请重新选择。")
        if selected_profile_cfg is not None:
            selected_profile, context_llm_cfg = selected_profile_cfg
            selected_model = selected_profile.model_id
        elif routing_cfgs is not None:
            context_llm_cfg = routing_cfgs.primary
        elif user is not None and resolve_user_llm(user) is not None:
            profiles = await list_llm_model_profiles(session, user_id=user.id)
            context_llm_cfg = with_model_profile_context(base_llm_cfg, profiles)
        else:
            context_llm_cfg = base_llm_cfg

        if effective_kb_id is None and get_settings().kb_auto_route_mode.strip().lower() != "off":
            readable_candidates = await list_readable_routable_kbs(
                session,
                user_id=user.id,
                limit=get_settings().kb_auto_route_max_candidates,
            )
            user_embedding_cfg = resolve_user_embedding(user)
            # A candidate whose embeddings cannot be produced for this user is
            # not routable. This preserves the old explicit-KB BYOK contract
            # without blocking ordinary chat merely because such a KB exists.
            route_candidates = [
                candidate
                for candidate in readable_candidates
                if candidate.is_system
                or bool(getattr(candidate, "embedding_provider", None))
                or user_embedding_cfg is not None
            ]

        kb: KB | None = None
        if effective_kb_id:
            kb = await session.get(KB, effective_kb_id)
            if kb is None:
                raise HTTPException(status_code=404, detail="kb not found")
            # v2-M9: any role (owner / editor / viewer) grants read access. System
            # KB returns "viewer" for everyone. None role = caller has no access,
            # answer 404 to avoid leaking existence.
            role = await kb.role_for(session, user.id)
            if role is None:
                raise HTTPException(status_code=404, detail="kb not found")
            # KB-mode chat needs embedding cfg too (search_kb embeds the query).
            # Skip the check for system KBs (they're read-only and predate BYOK).
            # v3-M7: also skip when the KB carries its own embedding cfg — the
            # caller doesn't need user-level cfg to use a KB that brings its own.
            if not kb.is_system and not bool(getattr(kb, "embedding_provider", None)):
                require_user_embedding(user)

        from src.adapters.observability import aspan

        # Root trace covers context assembly + agent run (flushed in run_agent).
        start_trace(
            "chat",
            conversation_id=conv.id if conv else None,
            user_id=user.id,
            input=(req.messages[-1].content if req.messages else None),
            metadata={
                "kb_id": effective_kb_id,
                "kb_auto_route_candidate_count": len(route_candidates),
                "model": selected_model,
                "user_email": user.email,
            },
        )

        if conv is not None:
            memory_trace: dict[str, Any] | None = None
            user_memory_embedding_cfg = resolve_user_embedding(user)
            async with aspan("build_context", metadata={"conversation_id": conv.id}):
                built = await build_context_for_conversation(
                    session,
                    conversation_id=conv.id,
                    user_id=user.id,
                    model=selected_model,
                    # Reserve RAG context for a route-capable unbound turn;
                    # the actual KB id is selected later by the Supervisor.
                    kb_id=effective_kb_id or ("__auto_route__" if route_candidates else None),
                    context_window=configured_context_window_for_model(
                        context_llm_cfg,
                        selected_model or (context_llm_cfg.default_model if context_llm_cfg else None),
                    ),
                    llm_cfg=context_llm_cfg,
                    embedding_cfg=user_memory_embedding_cfg,
                )
            messages = built.messages
            memory_trace = built.memory_trace
        elif req.messages:
            messages = [{"role": m.role, "content": m.content} for m in req.messages]
            memory_trace = None
        else:
            raise HTTPException(
                status_code=400,
                detail="messages or conversation_id is required",
            )

        async def persist_auto_kb_binding(selected_kb: KB, _route: dict[str, Any]) -> None:
            """Persist only a supervisor-accepted, ACL-scoped selection."""
            if conv is None:
                return
            from src.adapters.persistence import get_session_factory

            factory = get_session_factory()
            async with factory() as write_session:
                stored = await write_session.get(Conversation, conv.id)
                if stored is not None and stored.user_id == user.id and stored.kb_id is None:
                    stored.kb_id = selected_kb.id
                    await write_session.commit()

        return run_chat_session(
            messages,
            rate_key=f"user:{user.id}",
            user_email=user.email,
            kb=kb,
            user=user,
            model_override=selected_model,
            memory_trace=memory_trace,
            conversation_lock_id=conversation_lock_id,
            conversation_id=conv.id if conv else None,
            llm_cfg_override=context_llm_cfg,
            complex_llm_cfg_override=None if selected_model else (routing_cfgs.complex if routing_cfgs else None),
            triage_llm_cfg_override=None if selected_model else (routing_cfgs.triage if routing_cfgs else None),
            fallback_llm_cfg_override=None if selected_model else (routing_cfgs.fallback if routing_cfgs else None),
            kb_candidates=route_candidates,
            on_kb_routed=persist_auto_kb_binding if conv is not None else None,
        )
    except Exception:
        if conversation_lock_id:
            await generation_lock.release(conversation_lock_id)
        from src.adapters.observability import get_current_trace

        orphan = get_current_trace()
        if orphan is not None and not orphan._finished:
            await orphan.finish(status="error", error="request_aborted")
        raise
