"""FastAPI entry — SSE chat endpoint + auth routes.

POST /api/chat takes conversation_id or full message history (multi-turn).
Auth: /api/auth/{register,login,me}; chat requires Bearer JWT when enabled.
Optional kb_id binds the agent to KB search (no travel tools).
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import replace as dc_replace
from typing import Any, AsyncGenerator, Literal

import structlog
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import build_graph
from src.agent.nodes import EMPTY_ANSWER_FALLBACK
from src.auth.middleware import CurrentUser
from src.auth.models import User
from src.auth.routes import router as auth_router
from src.conversations.context import build_context_for_conversation
from src.conversations.models import Conversation
from src.conversations.routes import router as conversations_router
from src.infra.database import get_session, init_db
from src.infra.llm import normalize_model_name
from src.infra.rate_limit import check as rate_check
from src.infra import generation_lock
from src.kb.models import KB
from src.kb.routes import router as kb_router
from src.safety.input_filter import sanitize_user_input
from src.safety.output_filter import redact_sensitive_output
from src.safety.prompt_injection import assess_prompt_injection
from src.observability import get_current_trace_id, start_trace
from src.settings import get_settings
from src.settings_user import (
    configured_context_window_for_model,
    list_llm_model_profiles,
    resolve_llm_profile_config,
    resolve_user_llm_routing_configs,
    require_user_embedding,
    require_user_llm,
    resolve_user_embedding,
    resolve_user_llm,
    resolve_user_reranker,
    resolve_system_llm,
    with_model_profile_context,
)

logging.basicConfig(level=logging.INFO)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    log.info("startup", env=get_settings().app_env)
    await init_db()
    log.info("db_ready")
    from src.kb.system_seed import seed_system_kbs

    await seed_system_kbs()
    log.info("system_kbs_seeded")

    from src.auth.admin_seed import seed_admins

    await seed_admins()
    log.info("admins_seeded")
    yield
    log.info("shutdown")


app = FastAPI(title="Agenora", version="3.1.0", lifespan=lifespan)

s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(kb_router)
app.include_router(conversations_router)

from src.settings_user.routes import router as settings_router  # noqa: E402

app.include_router(settings_router)

from src.admin.routes import router as admin_router  # noqa: E402

app.include_router(admin_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "3.1.0"}


# ---------------------------------------------------------------------------
# Chat schemas
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] | None = Field(default=None)
    conversation_id: str | None = Field(default=None, max_length=36)
    kb_id: str | None = Field(default=None, description="Bind to a KB; agent uses search_kb only")
    # v3-M6: optional per-request LLM model override. Frontend reads
    # currentConv.llm_model (saved per-conversation in DB) and passes it here.
    # Server applies via dataclasses.replace() — no schema-level dependency.
    model: str | None = Field(default=None, max_length=128)
    # v5: stable user-owned model profile.  Unlike ``model`` this also
    # resolves the provider credentials, so two connections may safely expose
    # the same remote model identifier.
    model_profile_id: str | None = Field(default=None, max_length=36)


# ---------------------------------------------------------------------------
# Shared session runner — used by POST /api/chat
# ---------------------------------------------------------------------------
def _run_chat_session(
    messages: list[dict[str, str]],
    rate_key: str,
    user_email: str | None = None,
    *,
    kb: KB | None = None,
    user: User | None = None,
    model_override: str | None = None,
    memory_trace: dict[str, Any] | None = None,
    conversation_lock_id: str | None = None,
    conversation_id: str | None = None,
    llm_cfg_override=None,
    complex_llm_cfg_override=None,
    triage_llm_cfg_override=None,
    fallback_llm_cfg_override=None,
) -> EventSourceResponse:
    settings = get_settings()
    allowed, remaining = rate_check(rate_key, settings.rate_limit_per_hour)
    if not allowed:
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    if not messages or messages[-1]["role"] != "user":
        raise HTTPException(
            status_code=400,
            detail="messages must be non-empty and end with role='user'",
        )

    last_user_content = messages[-1]["content"]
    cleaned, blocked = sanitize_user_input(last_user_content)
    if blocked:
        raise HTTPException(status_code=400, detail=f"input_blocked: {blocked}")
    prompt_guard = assess_prompt_injection(cleaned)
    if prompt_guard.level != "low":
        log.warning(
            "prompt_injection_detected",
            prompt_injection_risk=prompt_guard.level,
            prompt_injection_reasons=prompt_guard.reasons,
            user_email=user_email,
            conversation_id=conversation_id,
        )

    full_messages = messages[:-1] + [{"role": "user", "content": cleaned}]

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(evt: dict[str, Any]) -> None:
        await queue.put(evt)

    # Per-user LLM wins; otherwise use the env-backed platform config.
    llm_cfg = llm_cfg_override or ((resolve_user_llm(user) if user is not None else None) or resolve_system_llm())
    # A per-conversation model override means "force this exact model".
    # Automatic default/complex routing is used only when no override is set.
    if model_override and llm_cfg is not None:
        llm_cfg = dc_replace(
            llm_cfg, default_model=model_override, complex_model=model_override
        )
    # v3-M7: embedding + reranker cfgs are KB-level when a KB is selected
    # (KB row carries its own creds → KB cfg wins; else fall back to user cfg).
    # For unbound chat (no KB), there's nothing to embed so user cfg is fine.
    if kb is not None and user is not None:
        from src.settings_user.kb_resolvers import (
            resolve_kb_embedding,
            resolve_kb_reranker,
        )
        embedding_cfg = resolve_kb_embedding(kb, user)
        reranker_cfg = resolve_kb_reranker(kb, user)
    else:
        embedding_cfg = resolve_user_embedding(user) if user is not None else None
        # v3-M4: per-user reranker override (opt-in, default None). Returned None
        # both when the user hasn't saved a config AND when the enable toggle is
        # off, so KBSearchTool can use this as the single skip-rerank signal.
        reranker_cfg = resolve_user_reranker(user) if user is not None else None
    # v2-M6: per-user KB-mode web_search opt-in flag.
    kb_web_search_enabled = bool(getattr(user, "kb_web_search_enabled", False))
    triage_llm_cfg = triage_llm_cfg_override
    if triage_llm_cfg is None and llm_cfg is not None and llm_cfg.triage_model:
        triage_llm_cfg = dc_replace(
            llm_cfg,
            default_model=llm_cfg.triage_model,
            complex_model=llm_cfg.triage_model,
            complex_enabled=False,
        )
    graph, cost = build_graph(
        emit=emit,
        kb=kb,
        llm_cfg=llm_cfg,
        complex_llm_cfg=complex_llm_cfg_override,
        fallback_llm_cfg=fallback_llm_cfg_override,
        triage_llm_cfg=triage_llm_cfg,
        embedding_cfg=embedding_cfg,
        reranker_cfg=reranker_cfg,
        kb_web_search_enabled=kb_web_search_enabled,
    )

    # The browser gets this safe, user-owned snapshot before the agent begins.
    # Never place raw system prompts, tool schemas, credentials, or prompt-guard
    # reasons here: those remain server-only / admin-trace data.
    if memory_trace is not None:
        from src.kb.models import SYSTEM_TRAVEL_KB_ID

        mode = (
            "general"
            if kb is None
            else "travel"
            if kb.id == SYSTEM_TRAVEL_KB_ID
            else "knowledge_base"
        )
        memory_trace = {
            **memory_trace,
            "runtime": {
                "mode": mode,
                "safety": "heightened" if prompt_guard.level != "low" else "standard",
            },
        }

    async def run_agent() -> None:
        nonlocal memory_trace
        from src.observability import get_current_trace

        trace = get_current_trace()
        if trace is None:
            trace = start_trace(
                "chat",
                conversation_id=conversation_id,
                user_id=user.id if user is not None else None,
                input=cleaned,
                metadata={
                    "kb_id": kb.id if kb else None,
                    "model": model_override,
                    "user_email": user_email,
                },
            )
        else:
            # Refresh input after sanitize when trace started earlier in chat_post.
            from src.settings import get_settings as _gs
            from src.observability.preview import preview_text

            if cleaned:
                trace.input_preview = preview_text(
                    cleaned, store_io=_gs().trace_store_io
                )
        final_state: dict[str, Any] | None = None
        try:
            if memory_trace is not None:
                await queue.put(
                    {
                        "event": "context_ready",
                        "memory_trace": memory_trace,
                    }
                )
            initial_state: dict[str, Any] = {
                "messages": full_messages,
                "iterations": 0,
                "tool_call_log": [],
                "citations": [],
                "prompt_injection_risk": prompt_guard.level,
                "prompt_injection_reasons": prompt_guard.reasons,
                "rag_suspicious_chunks": 0,
                "rag_filtered_chunks": [],
            }
            final_state = await graph.ainvoke(initial_state)
            prompt_trace = final_state.get("prompt_trace")
            if memory_trace is not None and isinstance(prompt_trace, dict):
                block_trace = memory_trace.get("context_blocks") or {}
                tokens = prompt_trace.get("tokens")
                truncation = prompt_trace.get("truncation")
                if isinstance(tokens, dict) and isinstance(truncation, dict):
                    for name in ("profile", "memory", "summary"):
                        block = block_trace.get(name)
                        if not isinstance(block, dict):
                            continue
                        injected_tokens = int(block.get("injected_tokens") or 0)
                        tokens[name] = injected_tokens
                        truncation[name] = bool(block.get("truncated"))
                    # Profile, memory, and summary are now attached to the
                    # latest user turn as untrusted data. ``reason`` excludes
                    # their measured payload from history before this trace is
                    # emitted, so adding their own UI segments does not alter
                    # the total or double-count them.
                memory_trace = {**memory_trace, "prompt": prompt_trace}
                # Replace the early context snapshot before the answer is
                # persisted so the in-chat trace and durable message agree.
                await queue.put({"event": "context_ready", "memory_trace": memory_trace})
            report = redact_sensitive_output(final_state.get("final_report") or "")
            raw_cost_usd = final_state.get("cost_usd")
            cost_usd = round(raw_cost_usd, 6) if isinstance(raw_cost_usd, (int, float)) else None
            report_streamed = bool(final_state.get("report_streamed"))
            if not report.strip():
                # Last-resort guard: never end the SSE round with zero tokens.
                log.warning(
                    "empty_final_report user=%s kb_id=%s; using fallback copy",
                    user_email,
                    kb.id if kb else None,
                )
                report = EMPTY_ANSWER_FALLBACK
                report_streamed = False
            # Finish sinks before SSE "done" so client disconnect / task.cancel
            # cannot skip DB persist while Langfuse flush is in flight.
            if trace is not None:
                await asyncio.shield(
                    trace.finish(
                        status="ok",
                        output=report,
                        total_cost_usd=cost_usd,
                        metadata={
                            "prompt_injection_risk": final_state.get("prompt_injection_risk")
                            or "low",
                            "prompt_injection_reasons": list(
                                final_state.get("prompt_injection_reasons") or []
                            ),
                            "rag_suspicious_chunks": int(
                                final_state.get("rag_suspicious_chunks") or 0
                            ),
                            "rag_filtered_chunks": list(
                                final_state.get("rag_filtered_chunks") or []
                            ),
                            "prompt_trace": prompt_trace if isinstance(prompt_trace, dict) else None,
                        },
                    )
                )
            if not report_streamed:
                # Skill / non-stream paths still use fake chunking for UX.
                await queue.put({"event": "report_start"})
                for piece in _chunks(report, size=8):
                    await queue.put({"event": "token", "text": piece})
                    await asyncio.sleep(0.02)
            await queue.put(
                {
                    "event": "done",
                    "cost_usd": cost_usd,
                    "rate_remaining": remaining,
                    "kb_id": kb.id if kb else None,
                    "memory_trace": memory_trace,
                    "citations": list(final_state.get("citations") or []),
                    "trace_id": (trace.id if trace is not None else get_current_trace_id()),
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("agent_failed", user=user_email, kb_id=kb.id if kb else None)
            if trace is not None:
                try:
                    err_meta: dict[str, Any] = {
                        "prompt_injection_risk": prompt_guard.level,
                        "prompt_injection_reasons": list(prompt_guard.reasons),
                        "rag_suspicious_chunks": 0,
                        "rag_filtered_chunks": [],
                    }
                    if isinstance(final_state, dict):
                        err_meta = {
                            "prompt_injection_risk": final_state.get("prompt_injection_risk")
                            or prompt_guard.level,
                            "prompt_injection_reasons": list(
                                final_state.get("prompt_injection_reasons")
                                or prompt_guard.reasons
                            ),
                            "rag_suspicious_chunks": int(
                                final_state.get("rag_suspicious_chunks") or 0
                            ),
                            "rag_filtered_chunks": list(
                                final_state.get("rag_filtered_chunks") or []
                            ),
                        }
                    await asyncio.shield(
                        trace.finish(status="error", error=str(exc), metadata=err_meta)
                    )
                except Exception:  # noqa: BLE001
                    pass
            await queue.put({"event": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run_agent())

    async def event_gen() -> AsyncGenerator[dict[str, str], None]:
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                yield {"event": "message", "data": json.dumps(evt, ensure_ascii=False)}
        finally:
            if conversation_lock_id:
                await generation_lock.release(conversation_lock_id)
            if not task.done():
                task.cancel()

    return EventSourceResponse(event_gen(), ping=15)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/chat")
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
        effective_kb_id = req.kb_id if req.kb_id is not None else (conv.kb_id if conv else None)
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

        from src.observability import aspan

        # Root trace covers context assembly + agent run (flushed in run_agent).
        start_trace(
            "chat",
            conversation_id=conv.id if conv else None,
            user_id=user.id,
            input=(req.messages[-1].content if req.messages else None),
            metadata={
                "kb_id": effective_kb_id,
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
                    kb_id=effective_kb_id,
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

        return _run_chat_session(
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
        )
    except Exception:
        if conversation_lock_id:
            await generation_lock.release(conversation_lock_id)
        from src.observability import get_current_trace

        orphan = get_current_trace()
        if orphan is not None and not orphan._finished:
            await orphan.finish(status="error", error="request_aborted")
        raise


def _chunks(s: str, *, size: int) -> list[str]:
    return [s[i : i + size] for i in range(0, len(s), size)]
