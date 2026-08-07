"""FastAPI entry — SSE chat endpoint + auth routes.

M0: POST /api/chat takes full message history (multi-turn context).
M1: /api/auth/{register,login,me} + chat endpoint requires Bearer JWT.
M3: POST /api/chat optionally takes kb_id; when set, the agent runs in
    KB-bound mode (search_kb only, no travel tools).
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import replace as dc_replace
from typing import Any, AsyncGenerator, Literal

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import build_graph
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
from src.kb.routes import invitations_router
from src.kb.routes import router as kb_router
from src.safety.input_filter import sanitize_user_input
from src.safety.output_filter import redact_sensitive_output
from src.safety.prompt_injection import assess_prompt_injection
from src.observability import get_current_trace_id, start_trace
from src.settings import get_settings
from src.settings_user import (
    require_user_embedding,
    require_user_llm,
    resolve_user_embedding,
    resolve_user_llm,
    resolve_user_reranker,
    resolve_system_llm,
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
app.include_router(invitations_router)
app.include_router(conversations_router)

from src.settings_user.routes import router as settings_router  # noqa: E402

app.include_router(settings_router)

from src.admin.routes import router as admin_router  # noqa: E402

app.include_router(admin_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.0"}


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


# ---------------------------------------------------------------------------
# Shared session runner — used by both POST and the deprecated GET endpoint
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

    full_messages = messages[:-1] + [{"role": "user", "content": cleaned}]

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(evt: dict[str, Any]) -> None:
        await queue.put(evt)

    # Per-user LLM wins; otherwise use the env-backed platform config.
    llm_cfg = (resolve_user_llm(user) if user is not None else None) or resolve_system_llm()
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
    graph, cost = build_graph(
        emit=emit,
        kb=kb,
        llm_cfg=llm_cfg,
        embedding_cfg=embedding_cfg,
        reranker_cfg=reranker_cfg,
        kb_web_search_enabled=kb_web_search_enabled,
    )

    async def run_agent() -> None:
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
        try:
            initial_state: dict[str, Any] = {
                "messages": full_messages,
                "iterations": 0,
                "tool_call_log": [],
                "citations": [],
                "prompt_injection_risk": prompt_guard.level,
                "prompt_injection_reasons": prompt_guard.reasons,
                "rag_suspicious_chunks": 0,
            }
            final_state = await graph.ainvoke(initial_state)
            report = redact_sensitive_output(final_state.get("final_report") or "")
            cost_usd = round(final_state.get("cost_usd", 0.0), 6)
            report_streamed = bool(final_state.get("report_streamed"))
            # Finish sinks before SSE "done" so client disconnect / task.cancel
            # cannot skip DB persist while Langfuse flush is in flight.
            if trace is not None:
                await asyncio.shield(
                    trace.finish(
                        status="ok",
                        output=report,
                        total_cost_usd=cost_usd,
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
                    await asyncio.shield(
                        trace.finish(status="error", error=str(exc))
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
    require_user_llm(user)

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
        selected_model = normalize_model_name(req.model or (conv.llm_model if conv else None))

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
            context_llm_cfg = (resolve_user_llm(user) if user is not None else None) or resolve_system_llm()
            user_memory_embedding_cfg = resolve_user_embedding(user)
            async with aspan("build_context", metadata={"conversation_id": conv.id}):
                built = await build_context_for_conversation(
                    session,
                    conversation_id=conv.id,
                    user_id=user.id,
                    model=selected_model,
                    kb_id=effective_kb_id,
                    context_window=context_llm_cfg.context_window if context_llm_cfg is not None else None,
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
        )
    except Exception:
        if conversation_lock_id:
            await generation_lock.release(conversation_lock_id)
        from src.observability import get_current_trace

        orphan = get_current_trace()
        if orphan is not None and not orphan._finished:
            await orphan.finish(status="error", error="request_aborted")
        raise


@app.get("/api/chat", deprecated=True)
async def chat_get(q: str, request: Request) -> EventSourceResponse:
    """Deprecated single-turn endpoint (anonymous, IP-rate-limited).

    Kept for backward-compat smoke tests. New clients must use POST with auth.
    """
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    return _run_chat_session(
        [{"role": "user", "content": q}], rate_key=f"ip:{client_ip}"
    )


def _chunks(s: str, *, size: int) -> list[str]:
    return [s[i : i + size] for i in range(0, len(s), size)]
