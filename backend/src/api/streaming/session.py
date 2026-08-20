"""SSE chat session runner — graph invoke + event queue.

HTTP auth, conversation load, and BYOK gates live in ``routes.py``.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace as dc_replace
from typing import Any, AsyncGenerator

import structlog
from fastapi import HTTPException
from langgraph.types import Command
from sse_starlette.sse import EventSourceResponse

from src.harness.agents.supervisor import build_supervisor_graph
from src.harness.runtime.checkpoints import checkpoint_config, open_agent_checkpointer
from src.harness.contracts.runtime import RunContext, RunIdentity
from src.harness.runtime.agent_loop import EMPTY_ANSWER_FALLBACK
from src.capabilities.identity.models import User
from src.capabilities.conversations.models import Conversation, Message
from src.platform.persistence import get_session_factory
from src.platform.runtime import generation_lock
from src.platform.runtime.rate_limit import (
    check as rate_check,
    retry_after_seconds,
)
from src.capabilities.knowledge.domain.models import KB
from src.platform.observability import get_current_trace_id, preview_text, start_trace
from src.harness.policy.input_filter import sanitize_user_input
from src.harness.policy.output_filter import redact_sensitive_output
from src.harness.policy.prompt_injection import assess_prompt_injection
from src.settings import get_settings
from src.capabilities.settings.domain.models import (
    resolve_system_llm,
    resolve_user_embedding,
    resolve_user_llm,
    resolve_user_reranker,
)

log = structlog.get_logger()


def _persisted_tool_events(tool_log: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert server-side tool records to the safe timeline shape stored in chat.

    The browser can disconnect at any point; a durable assistant row must not
    depend on its transient SSE timeline. Deliberately omit raw tool results so
    service internals never become conversation content.
    """
    events: list[dict[str, Any]] = []
    for index, entry in enumerate(tool_log or []):
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        events.append(
            {
                "id": str(entry.get("id") or f"persisted-tool-{index}"),
                "name": name,
                "status": "error" if entry.get("error") else "ok",
                "latency_ms": entry.get("latency_ms"),
                "error": entry.get("error"),
            }
        )
    return events


def _human_interrupt_content(payload: dict[str, Any]) -> str:
    """Give a paused turn a durable, user-visible assistant message.

    The structured payload remains the source for the form, but an interrupt is
    still an assistant turn in the conversation transcript. Persisting its
    prompt prevents a blank row after reloads and exports.
    """
    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    return "请补充继续处理所需的信息。"


async def _persist_assistant_turn(
    *,
    conversation_id: str | None,
    user: User | None,
    content: str,
    tools: list[dict[str, Any]],
    cost_usd: float | None = None,
    memory_trace: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> str | None:
    """Persist an agent outcome before sending the terminal SSE event.

    This is intentionally server-owned: a tab reload cannot otherwise lose a
    completed refund result between the tool call and the frontend's own
    message-write request.
    """
    if not conversation_id or user is None:
        return None
    factory = get_session_factory()
    async with factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user.id:
            return None
        message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            role="assistant",
            content=content,
            tool_call_log=Message.encode_tool_call_log(tools, memory_trace=memory_trace, citations=citations),
            cost_usd=cost_usd,
        )
        session.add(message)
        await session.commit()
        return message.id


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
    kb_route_scope: str = "turn",
) -> EventSourceResponse:
    settings = get_settings()
    allowed, remaining = rate_check(rate_key, settings.rate_limit_per_hour)
    if not allowed:
        retry_after = retry_after_seconds(rate_key)
        retry_minutes = max(1, (retry_after + 59) // 60)
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limit_exceeded",
                "message": f"操作过于频繁，请约 {retry_minutes} 分钟后再试。",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

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
    workflow_config = (
        checkpoint_config(user_id=user.id if user is not None else None, conversation_id=conversation_id)
        if conversation_id
        else None
    )
    def build_graph(*, checkpointer=None):
        return build_supervisor_graph(
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
            kb_route_scope=kb_route_scope,
            run_context=run_context,
            allow_rag_chat_handoff=bool(settings.agent_allow_rag_chat_handoff),
            checkpointer=checkpointer,
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
        from src.platform.observability import get_current_trace

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
                "human_inputs": {},
                "human_required_slots": [],
                "human_gate_resumed": False,
                "pending_confirmation": None,
            }
            if workflow_config is not None:
                async with open_agent_checkpointer() as checkpointer:
                    graph, _cost = build_graph(checkpointer=checkpointer)
                    snapshot = await graph.aget_state(workflow_config)
                    pending_interrupt = any(
                        bool(getattr(task, "interrupts", ())) for task in (snapshot.tasks or ())
                    )
                    final_state = await graph.ainvoke(
                        Command(resume=cleaned) if pending_interrupt else initial_state,
                        config=workflow_config,
                    )
            else:
                graph, _cost = build_graph()
                final_state = await graph.ainvoke(initial_state)

            interrupts = final_state.get("__interrupt__") if isinstance(final_state, dict) else None
            if isinstance(interrupts, list) and interrupts:
                first = interrupts[0]
                payload = getattr(first, "value", None)
                if not isinstance(payload, dict):
                    payload = {"kind": "human_input_required", "prompt": "请补充继续处理所需的信息。"}
                human_tool = {
                    "id": f"human-input-{uuid.uuid4()}",
                    "name": "human_input_required",
                    "status": "ok",
                    "input": payload,
                }
                persisted_message_id = await _persist_assistant_turn(
                    conversation_id=conversation_id,
                    user=user,
                    content=_human_interrupt_content(payload),
                    tools=[human_tool],
                )
                await queue.put({"event": "human_input_required", **payload})
                if trace is not None:
                    await asyncio.shield(
                        trace.finish(
                            status="ok",
                            output=str(payload.get("prompt") or ""),
                            metadata={"interrupted": True, "human_slot": payload.get("slot")},
                        )
                    )
                await queue.put(
                    {
                        "event": "done",
                        "interrupted": True,
                        "message_id": persisted_message_id,
                        "rate_remaining": remaining,
                        "trace_id": (trace.id if trace is not None else get_current_trace_id()),
                    }
                )
                return
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
            persisted_message_id = await _persist_assistant_turn(
                conversation_id=conversation_id,
                user=user,
                content=report,
                tools=_persisted_tool_events(final_state.get("tool_call_log")),
                cost_usd=cost_usd,
                memory_trace=memory_trace,
                citations=list(final_state.get("citations") or []),
            )
            await queue.put(
                {
                    "event": "done",
                    "cost_usd": cost_usd,
                    "message_id": persisted_message_id,
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
            if conversation_lock_id:
                await generation_lock.release(conversation_lock_id)

    task = asyncio.create_task(run_agent())

    async def event_gen() -> AsyncGenerator[dict[str, str], None]:
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                yield {"event": "message", "data": json.dumps(evt, ensure_ascii=False)}
        finally:
            # Do not cancel the agent when the browser refreshes. In particular,
            # refund confirmation is a high-risk write that must finish and
            # persist its outcome even if the SSE client reconnects later.
            # ``run_agent`` releases the generation lock after it has finished.
            if task.done() and not task.cancelled():
                task.exception()

    return EventSourceResponse(event_gen(), ping=15)


def _chunks(s: str, *, size: int) -> list[str]:
    return [s[i : i + size] for i in range(0, len(s), size)]
