"""Conversations, messages, and user-memory HTTP routes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.capabilities.identity.middleware import CurrentUser
from src.harness.context import (
    compute_budget,
    consolidate_user_memories,
    context_status_payload,
    estimate_effective_context_tokens,
    extract_conversation_memories,
    get_latest_summary,
    rag_reserve_for_kb,
    refresh_memory_embedding,
    run_memory_heavy_background,
    run_summary_prepare_background,
    store_user_memories,
)
from src.capabilities.conversations.models import Conversation, Message, UserMemory
from src.platform.persistence import get_session
from src.platform.llm import normalize_model_name
from src.capabilities.settings.domain.models import (
    configured_context_window_for_model,
    list_llm_model_profiles,
    resolve_llm_profile_config,
    resolve_system_llm,
    resolve_user_embedding,
    resolve_user_llm,
    with_model_profile_context,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    kb_id: str | None = Field(default=None, max_length=36)
    title: str | None = Field(default=None, max_length=128)


class PatchConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    kb_id: str | None = Field(default=None, max_length=36)
    llm_model: str | None = Field(default=None, max_length=128)
    llm_profile_id: str | None = Field(default=None, max_length=36)


class AppendMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="")
    tools: list[dict[str, Any]] | None = Field(default=None)
    # Ordered text/tool timeline for streamed assistant turns. This shares the
    # existing tool_call_log JSON column, so no DB migration is necessary.
    parts: list[dict[str, Any]] | None = Field(default=None)
    memory_trace: dict[str, Any] | None = Field(default=None)
    citations: list[dict[str, Any]] | None = Field(default=None)
    cost_usd: float | None = Field(default=None)
    error: str | None = Field(default=None, max_length=4096)


class PatchMemoryRequest(BaseModel):
    """Optional user control for a silently captured memory."""

    content: str | None = Field(default=None, min_length=4, max_length=500)
    value: str | None = Field(default=None, min_length=1, max_length=500)
    importance: float | None = Field(default=None, ge=0, le=1)
    status: Literal["active", "deleted"] | None = None
    # Explicit null clears expiry (long-lived). Omitted field leaves it unchanged.
    expires_at: datetime | None = None


class ImportMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = ""
    tools: list[dict[str, Any]] | None = None
    cost_usd: float | None = None
    error: str | None = None
    created_at: int | None = None


class ImportConversation(BaseModel):
    title: str = "新对话"
    kb_id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None
    messages: list[ImportMessage] = Field(default_factory=list)


class ImportRequest(BaseModel):
    conversations: list[ImportConversation] = Field(default_factory=list)


async def _load_owned_conversation(
    session: AsyncSession, conv_id: str, user_id: str
) -> Conversation:
    conv = await session.get(Conversation, conv_id)
    if conv is None or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


async def _build_context_status(
    session: AsyncSession,
    conv: Conversation,
    *,
    context_window: int | None = None,
) -> dict:
    result = await session.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )
    messages = list(result.scalars().all())
    budget = compute_budget(
        messages,
        conv.llm_model,
        context_window,
        rag_reserve=rag_reserve_for_kb(conv.kb_id),
    )
    summary = await get_latest_summary(session, conv.id)
    # Background prewarming must not make the UI report a conversation as
    # compressed before the normal 72% activation threshold is reached.
    if summary is not None and summary.is_prepared:
        summary = None
    from src.platform.llm.tokenizer import token_model_scope

    with token_model_scope(conv.llm_model):
        effective = estimate_effective_context_tokens(
            messages,
            summary,
            model=conv.llm_model,
            available_history_tokens=budget.available_history_tokens,
        )
    payload = context_status_payload(
        budget=budget,
        summary=summary,
        effective_tokens=effective,
    )
    covered_count = min(max(0, summary.covered_message_count), len(messages)) if summary else 0
    payload["recent_message_count"] = len(messages) - covered_count
    return payload


def _synchronize_memory_trace_after_completion(
    memory_trace: dict[str, Any] | None, context_status: dict[str, Any]
) -> dict[str, Any] | None:
    """Refresh the displayed trace after its assistant reply is persisted.

    Prompt metadata is initially captured before generation.  The response then
    becomes part of the conversation, so leaving that snapshot untouched makes
    the assistant-card trace disagree with the composer card.  Keep the stable
    request categories, but advance raw history and the reconstructed total to
    the same persisted-session snapshot used by context status.
    """
    if not isinstance(memory_trace, dict):
        return memory_trace
    trace = json.loads(json.dumps(memory_trace, ensure_ascii=False))
    trace["recent_message_count"] = max(0, int(context_status.get("recent_message_count") or 0))
    prompt = trace.get("prompt")
    if not isinstance(prompt, dict):
        return trace
    tokens = prompt.get("tokens")
    if not isinstance(tokens, dict):
        return trace
    previous_history = max(0, int(tokens.get("history") or 0))
    summary_tokens = max(0, int(tokens.get("summary") or 0))
    current_effective = max(0, int(context_status.get("current_tokens") or 0))
    synced_history = max(0, current_effective - summary_tokens)
    tokens["history"] = synced_history
    tokens["total_input"] = max(
        0, int(tokens.get("total_input") or 0) + synced_history - previous_history
    )
    prompt["context_window"] = max(0, int(context_status.get("context_window") or 0))
    return trace


async def _context_cfg_for_user(session: AsyncSession, user: CurrentUser):
    cfg = resolve_user_llm(user) or resolve_system_llm()
    if resolve_user_llm(user) is not None:
        profiles = await list_llm_model_profiles(session, user_id=user.id)
        return with_model_profile_context(cfg, profiles)
    return cfg


async def _context_cfg_for_conversation(
    session: AsyncSession, conv: Conversation, user: CurrentUser
):
    selected = await resolve_llm_profile_config(
        session, user=user, profile_id=conv.llm_profile_id
    )
    if selected is not None:
        return selected[1]
    return await _context_cfg_for_user(session, user)


def _derive_title(content: str) -> str:
    cleaned = " ".join(content.strip().split())
    if not cleaned:
        return "新对话"
    return cleaned[:24] + "..." if len(cleaned) > 24 else cleaned


def _is_default_title(title: str) -> bool:
    return not title or title in {"新对话", "Untitled", ""}


def _ms_to_dt(ms: int | None) -> datetime | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


@router.get("")
async def list_conversations(
    user: CurrentUser,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    session: AsyncSession = Depends(get_session),
) -> list[dict] | dict:
    from sqlalchemy import or_

    base = select(Conversation).where(Conversation.user_id == user.id)
    needle = (q or "").strip()
    if needle:
        # Escape LIKE wildcards so user input is literal.
        escaped = (
            needle.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        message_match = (
            select(Message.id)
            .where(
                Message.conversation_id == Conversation.id,
                Message.content.ilike(pattern, escape="\\"),
            )
            .correlate(Conversation)
            .exists()
        )
        base = base.where(
            or_(
                Conversation.title.ilike(pattern, escape="\\"),
                message_match,
            )
        )
    base = base.order_by(desc(Conversation.updated_at))

    if page is None:
        result = await session.execute(base)
        return [c.to_summary_dict() for c in result.scalars().all()]

    count_stmt = (
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user.id)
    )
    if needle:
        count_stmt = (
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.user_id == user.id)
            .where(
                or_(
                    Conversation.title.ilike(pattern, escape="\\"),
                    (
                        select(Message.id)
                        .where(
                            Message.conversation_id == Conversation.id,
                            Message.content.ilike(pattern, escape="\\"),
                        )
                        .correlate(Conversation)
                        .exists()
                    ),
                )
            )
        )
    total = (await session.execute(count_stmt)).scalar_one()
    result = await session.execute(base.offset((page - 1) * page_size).limit(page_size))
    items = [c.to_summary_dict() for c in result.scalars().all()]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.delete("", status_code=status.HTTP_200_OK)
async def delete_all_conversations(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await session.execute(delete(Conversation).where(Conversation.user_id == user.id))
    await session.commit()
    return {"ok": True}


@router.get("/export")
async def export_conversations(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    convs_result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(desc(Conversation.updated_at))
    )
    convs = convs_result.scalars().all()
    out: list[dict] = []
    for c in convs:
        msgs_result = await session.execute(
            select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)
        )
        msgs = msgs_result.scalars().all()
        out.append(
            {
                "id": c.id,
                "title": c.title,
                "kb_id": c.kb_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "messages": [m.to_public_dict() for m in msgs],
            }
        )
    return JSONResponse(
        out,
        headers={"Content-Disposition": 'attachment; filename="agenora-export.json"'},
    )


@router.get("/memories")
async def list_memories(
    user: CurrentUser,
    status_filter: Literal["active", "superseded", "deleted", "expired", "all"] = Query(
        default="active", alias="status"
    ),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    where = [UserMemory.user_id == user.id]
    if status_filter != "all":
        where.append(UserMemory.status == status_filter)
    result = await session.execute(
        select(UserMemory)
        .where(*where)
        .order_by(desc(UserMemory.updated_at))
    )
    return [m.to_public_dict() for m in result.scalars().all()]


@router.get("/memories/export")
async def export_memories(
    user: CurrentUser,
    status_filter: Literal["active", "superseded", "deleted", "expired", "all"] = Query(
        default="all", alias="status"
    ),
    session: AsyncSession = Depends(get_session),
):
    """Download the caller's memories as a portable JSON file."""
    where = [UserMemory.user_id == user.id]
    if status_filter != "all":
        where.append(UserMemory.status == status_filter)
    result = await session.execute(
        select(UserMemory)
        .where(*where)
        .order_by(desc(UserMemory.updated_at))
    )
    rows = [m.to_public_dict() for m in result.scalars().all()]
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id,
        "status_filter": status_filter,
        "count": len(rows),
        "memories": rows,
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": 'attachment; filename="agenora-memories.json"'},
    )


@router.delete(
    "/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_memory(
    memory_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(UserMemory, memory_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="memory not found")
    row.status = "deleted"
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()


def _normalize_memory_expires_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if value > now + timedelta(days=3650):
        raise HTTPException(status_code=400, detail="expires_at too far in the future")
    return value.astimezone(timezone.utc)


@router.patch("/memories/{memory_id}")
async def patch_memory(
    memory_id: str,
    req: PatchMemoryRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await session.get(UserMemory, memory_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="memory not found")
    if req.content is not None:
        row.content = req.content.strip()
        row.source = "user_edited"
        row.confidence = 1.0
        row.embedding_json = None
        row.embedding_fingerprint = None
    if req.value is not None:
        row.memory_value = req.value.strip()
        row.source = "user_edited"
        row.confidence = 1.0
    if req.importance is not None:
        row.importance = req.importance
    if req.status is not None:
        row.status = req.status
    if "expires_at" in req.model_fields_set:
        row.expires_at = _normalize_memory_expires_at(req.expires_at)
        row.source = "user_edited"
        now = datetime.now(timezone.utc)
        if row.expires_at is None and row.status == "expired":
            row.status = "active"
        elif row.expires_at is not None and row.expires_at <= now and row.status == "active":
            row.status = "expired"
    row.updated_at = datetime.now(timezone.utc)
    if req.content is not None:
        await refresh_memory_embedding(row, embedding_cfg=resolve_user_embedding(user))
    await consolidate_user_memories(session, user_id=user.id)
    await session.commit()
    await session.refresh(row)
    return row.to_public_dict()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    req: CreateConversationRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = Conversation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title=(req.title or "新对话").strip()[:128] or "新对话",
        kb_id=req.kb_id,
    )
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv.to_dict_with_messages()


@router.get("/{conv_id}")
async def get_conversation(
    conv_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _load_owned_conversation(session, conv_id, user.id)
    payload = conv.to_dict_with_messages()
    llm_cfg = await _context_cfg_for_conversation(session, conv, user)
    payload["context_status"] = await _build_context_status(
        session,
        conv,
        context_window=configured_context_window_for_model(
            llm_cfg, conv.llm_model or (llm_cfg.default_model if llm_cfg else None)
        ),
    )
    return payload


@router.get("/{conv_id}/context-status")
async def get_conversation_context_status(
    conv_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _load_owned_conversation(session, conv_id, user.id)
    llm_cfg = await _context_cfg_for_conversation(session, conv, user)
    return await _build_context_status(
        session,
        conv,
        context_window=configured_context_window_for_model(
            llm_cfg, conv.llm_model or (llm_cfg.default_model if llm_cfg else None)
        ),
    )


@router.post("/{conv_id}/finalize")
async def finalize_conversation(
    conv_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _load_owned_conversation(session, conv_id, user.id)
    if conv.finalized_at is not None:
        return {
            "already_finalized": True,
            "conversation": conv.to_summary_dict(),
            "memory": {
                "messages_scanned": 0,
                "rule_candidates": 0,
                "llm_candidates": 0,
                "stored": 0,
            },
        }

    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Conversation)
        .where(
            Conversation.id == conv.id,
            Conversation.user_id == user.id,
            Conversation.finalized_at.is_(None),
        )
        .values(finalized_at=now, updated_at=now)
    )
    if not result.rowcount:
        await session.rollback()
        await session.refresh(conv)
        return {
            "already_finalized": True,
            "conversation": conv.to_summary_dict(),
            "memory": {
                "messages_scanned": 0,
                "rule_candidates": 0,
                "llm_candidates": 0,
                "stored": 0,
            },
        }

    memory = await extract_conversation_memories(
        session,
        conversation_id=conv.id,
        user_id=user.id,
        kb_id=conv.kb_id,
        llm_cfg=resolve_user_llm(user) or resolve_system_llm(),
        embedding_cfg=resolve_user_embedding(user),
    )
    await session.commit()
    await session.refresh(conv)
    return {"already_finalized": False, "conversation": conv.to_summary_dict(), "memory": memory}


@router.patch("/{conv_id}")
async def patch_conversation(
    conv_id: str,
    req: PatchConversationRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _load_owned_conversation(session, conv_id, user.id)

    fields_set = req.model_fields_set
    if "title" in fields_set and req.title is not None:
        title = req.title.strip()[:128]
        if title:
            conv.title = title
    if "kb_id" in fields_set:
        conv.kb_id = req.kb_id
    if "llm_profile_id" in fields_set:
        if req.llm_profile_id is None:
            conv.llm_profile_id = None
            conv.llm_model = None
        else:
            selected = await resolve_llm_profile_config(
                session, user=user, profile_id=req.llm_profile_id
            )
            if selected is None:
                raise HTTPException(status_code=422, detail="所选模型档案不可用，请重新选择。")
            profile, _ = selected
            conv.llm_profile_id = profile.id
            conv.llm_model = profile.model_id
    elif "llm_model" in fields_set:
        conv.llm_model = normalize_model_name(req.llm_model)
        # Legacy clients posting only a raw model continue to work, but an
        # explicit profile takes precedence as soon as the new UI selects one.
        conv.llm_profile_id = None

    selection_changed = bool({"llm_profile_id", "llm_model"} & fields_set)
    await session.commit()
    await session.refresh(conv)
    payload = conv.to_summary_dict()
    if selection_changed:
        llm_cfg = await _context_cfg_for_conversation(session, conv, user)
        payload["context_status"] = await _build_context_status(
            session,
            conv,
            context_window=configured_context_window_for_model(
                llm_cfg, conv.llm_model or (llm_cfg.default_model if llm_cfg else None)
            ),
        )
    return payload


@router.delete(
    "/{conv_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_conversation(
    conv_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    conv = await _load_owned_conversation(session, conv_id, user.id)
    await session.delete(conv)
    await session.commit()


@router.post("/{conv_id}/messages", status_code=status.HTTP_201_CREATED)
async def append_message(
    conv_id: str,
    req: AppendMessageRequest,
    user: CurrentUser,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _load_owned_conversation(session, conv_id, user.id)
    content = req.content or ""
    tools = req.tools or []
    parts = req.parts or []
    error = req.error or None
    if req.role != "assistant" and parts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="parts are assistant-only",
        )
    if req.role == "assistant" and not content.strip() and not tools and not error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="assistant message must include content, tools, or error",
        )

    msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        role=req.role,
        content=content,
        tool_call_log=Message.encode_tool_call_log(
            tools, parts, req.memory_trace, req.citations
        ),
        cost_usd=req.cost_usd,
        error=error,
    )
    session.add(msg)
    await session.flush()

    pending_memory_ids: list[str] = []
    embedding_cfg = None
    if req.role == "user":
        embedding_cfg = resolve_user_embedding(user)
        # Hot path: relational write only. Embedding + consolidate run after commit.
        stored = await store_user_memories(
            session,
            user_id=user.id,
            message_id=msg.id,
            content=content,
            kb_id=conv.kb_id,
            embedding_cfg=embedding_cfg,
            heavy=False,
        )
        pending_memory_ids = [row.id for row in stored]
        if _is_default_title(conv.title) and req.content.strip():
            conv.title = _derive_title(req.content)

    conv.updated_at = datetime.now(timezone.utc)
    conv.finalized_at = None

    if req.role == "assistant" and req.memory_trace:
        trace_llm_cfg = await _context_cfg_for_conversation(session, conv, user)
        trace_model = conv.llm_model or (
            trace_llm_cfg.default_model if trace_llm_cfg is not None else None
        )
        trace_status = await _build_context_status(
            session,
            conv,
            context_window=configured_context_window_for_model(trace_llm_cfg, trace_model),
        )
        synced_trace = _synchronize_memory_trace_after_completion(req.memory_trace, trace_status)
        msg.tool_call_log = Message.encode_tool_call_log(
            tools, parts, synced_trace, req.citations
        )

    await session.commit()
    await session.refresh(msg)
    if pending_memory_ids:
        background.add_task(
            run_memory_heavy_background,
            user.id,
            pending_memory_ids,
            embedding_cfg,
        )
    summary_llm_cfg = await _context_cfg_for_conversation(session, conv, user)
    summary_model = conv.llm_model or (
        summary_llm_cfg.default_model if summary_llm_cfg is not None else None
    )
    background.add_task(
        run_summary_prepare_background,
        conv.id,
        summary_model,
        configured_context_window_for_model(summary_llm_cfg, summary_model),
        summary_llm_cfg,
    )
    return msg.to_public_dict()


@router.post("/import")
async def import_conversations(
    req: ImportRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    imported = 0
    for c in req.conversations:
        c_created = _ms_to_dt(c.created_at) or datetime.now(timezone.utc)
        c_updated = _ms_to_dt(c.updated_at) or c_created
        title = (c.title or "新对话").strip()[:128] or "新对话"
        if _is_default_title(title):
            for m in c.messages:
                if m.role == "user" and m.content.strip():
                    title = _derive_title(m.content)
                    break

        conv = Conversation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            title=title,
            kb_id=c.kb_id,
            created_at=c_created,
            updated_at=c_updated,
        )
        session.add(conv)
        await session.flush()

        for m in c.messages:
            if (
                m.role == "assistant"
                and not (m.content or "").strip()
                and not (m.tools or [])
                and not (m.error or None)
            ):
                continue
            m_created = _ms_to_dt(m.created_at) or c_created
            session.add(
                Message(
                    id=str(uuid.uuid4()),
                    conversation_id=conv.id,
                    role=m.role,
                    content=m.content or "",
                    tool_call_log=json.dumps(m.tools, ensure_ascii=False) if m.tools else None,
                    cost_usd=m.cost_usd,
                    error=m.error or None,
                    created_at=m_created,
                )
            )
        imported += 1

    await session.commit()
    return {"imported": imported}
