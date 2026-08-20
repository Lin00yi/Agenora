"""SSE chat session runner — graph invoke + event queue.

HTTP auth, conversation load, and BYOK gates live in ``routes.py``.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace as dc_replace
from typing import Any, AsyncGenerator

import structlog
from fastapi import HTTPException
from sse_starlette.sse import EventSourceResponse

from src.agents.supervisor import build_supervisor_graph
from src.harness.contracts.runtime import RunContext, RunIdentity
from src.runtime.agent_loop import EMPTY_ANSWER_FALLBACK
from src.auth.models import User
from src.infra import generation_lock
from src.infra.rate_limit import check as rate_check
from src.capabilities.knowledge.domain.models import KB
from src.adapters.observability import get_current_trace_id, preview_text, start_trace
from src.safety.input_filter import sanitize_user_input
from src.safety.output_filter import redact_sensitive_output
from src.safety.prompt_injection import assess_prompt_injection
from src.settings import get_settings
from src.capabilities.settings.domain.models import (
    resolve_system_llm,
    resolve_user_embedding,
    resolve_user_llm,
    resolve_user_reranker,
)

log = structlog.get_logger()


def run_chat_session(
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
    kb_candidates: list[KB] | None = None,
    on_kb_routed=None,
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
        from src.capabilities.knowledge.application.configuration import (
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

    def configure_routed_kb(selected_kb: KB) -> dict[str, Any]:
        """Switch runtime-only retrieval dependencies after DAG routing."""
        if user is None:
            return {}
        from src.capabilities.knowledge.application.configuration import (
            resolve_kb_embedding,
            resolve_kb_reranker,
        )

        return {
            "embedding_cfg": resolve_kb_embedding(selected_kb, user),
            "reranker_cfg": resolve_kb_reranker(selected_kb, user),
            "kb_web_search_enabled": bool(getattr(user, "kb_web_search_enabled", False)),
        }
    triage_llm_cfg = triage_llm_cfg_override
    if triage_llm_cfg is None and llm_cfg is not None and llm_cfg.triage_model:
        triage_llm_cfg = dc_replace(
            llm_cfg,
            default_model=llm_cfg.triage_model,
            complex_model=llm_cfg.triage_model,
            complex_enabled=False,
        )
    run_context = RunContext(
        identity=RunIdentity(
            user_id=user.id if user is not None else None,
            conversation_id=conversation_id,
        ),
        emit=emit,
    )
    graph, _cost = build_supervisor_graph(
        emit=emit,
        kb=kb,
        llm_cfg=llm_cfg,
        complex_llm_cfg=complex_llm_cfg_override,
        fallback_llm_cfg=fallback_llm_cfg_override,
        triage_llm_cfg=triage_llm_cfg,
        embedding_cfg=embedding_cfg,
        reranker_cfg=reranker_cfg,
        kb_web_search_enabled=kb_web_search_enabled,
        kb_candidates=kb_candidates,
        configure_routed_kb=configure_routed_kb if kb_candidates else None,
        on_kb_routed=on_kb_routed,
        run_context=run_context,
        allow_rag_chat_handoff=bool(settings.agent_allow_rag_chat_handoff),
    )

    # The browser gets this safe, user-owned snapshot before the agent begins.
    # Never place raw system prompts, tool schemas, credentials, or prompt-guard
    # reasons here: those remain server-only / admin-trace data.
    if memory_trace is not None:
        mode = "general" if kb is None else "knowledge_base"
        memory_trace = {
            **memory_trace,
            "runtime": {
                "mode": mode,
                "agent_runtime": "supervisor",
                "safety": "heightened" if prompt_guard.level != "low" else "standard",
            },
        }

    async def run_agent() -> None:
        nonlocal memory_trace
        from src.adapters.observability import get_current_trace

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
                "base_messages": list(full_messages),
                "iterations": 0,
                "tool_call_log": [],
                "citations": [],
                "prompt_injection_risk": prompt_guard.level,
                "prompt_injection_reasons": prompt_guard.reasons,
                "rag_suspicious_chunks": 0,
                "rag_filtered_chunks": [],
                "kb_id": kb.id if kb else None,
                "agent_results": {},
                "handoff_count": 0,
                "supervisor_trace": [],
            }
            final_state = await graph.ainvoke(initial_state)
            final_kb_id = final_state.get("kb_id") or (kb.id if kb else None)
            final_kb_route = final_state.get("kb_auto_route")
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
                memory_trace = {
                    **memory_trace,
                    "prompt": prompt_trace,
                    **({"kb_route": final_kb_route} if isinstance(final_kb_route, dict) else {}),
                }
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
                            "kb_auto_route": final_kb_route,
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
                    "kb_id": final_kb_id,
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
                        "kb_auto_route": final_state.get("kb_auto_route") if isinstance(final_state, dict) else None,
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
                            "kb_auto_route": final_state.get("kb_auto_route"),
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


def _chunks(s: str, *, size: int) -> list[str]:
    return [s[i : i + size] for i in range(0, len(s), size)]
