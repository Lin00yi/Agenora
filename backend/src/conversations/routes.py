"""Conversations, messages, and user-memory HTTP routes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.middleware import CurrentUser
from src.conversations.context import (
    compute_budget,
    consolidate_user_memories,
    context_status_payload,
    get_latest_summary,
    refresh_memory_embedding,
    store_user_memories,
)
from src.conversations.models import Conversation, Message, UserMemory
from src.infra.database import get_session
from src.infra.llm import normalize_model_name
from src.settings_user import resolve_user_embedding, resolve_user_llm

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    kb_id: str | None = Field(default=None, max_length=36)
    title: str | None = Field(default=None, max_length=128)


class PatchConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    kb_id: str | None = Field(default=None, max_length=36)
    llm_model: str | None = Field(default=None, max_length=128)


class AppendMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="")
    tools: list[dict[str, Any]] | None = Field(default=None)
    cost_usd: float | None = Field(default=None)
    error: str | None = Field(default=None, max_length=4096)


class PatchMemoryRequest(BaseModel):
    """Optional user control for a silently captured memory."""

    content: str | None = Field(default=None, min_length=4, max_length=500)
    value: str | None = Field(default=None, min_length=1, max_length=500)
    importance: float | None = Field(default=None, ge=0, le=1)
    status: Literal["active", "deleted"] | None = None


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
    budget = compute_budget(messages, conv.llm_model, context_window)
    summary = await get_latest_summary(session, conv.id)
    return context_status_payload(budget=budget, summary=summary)


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
    session: AsyncSession = Depends(get_session),
) -> list[dict] | dict:
    base = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(desc(Conversation.updated_at))
    )
    if page is None:
        result = await session.execute(base)
        return [c.to_summary_dict() for c in result.scalars().all()]

    total = (
        await session.execute(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user.id)
        )
    ).scalar_one()
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
        headers={"Content-Disposition": 'attachment; filename="anykb-export.json"'},
    )


@router.get("/memories")
async def list_memories(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    result = await session.execute(
        select(UserMemory)
        .where(UserMemory.user_id == user.id, UserMemory.status == "active")
        .order_by(desc(UserMemory.updated_at))
    )
    return [m.to_public_dict() for m in result.scalars().all()]


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
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
    llm_cfg = resolve_user_llm(user)
    payload["context_status"] = await _build_context_status(
        session, conv, context_window=llm_cfg.context_window if llm_cfg else None
    )
    return payload


@router.get("/{conv_id}/context-status")
async def get_conversation_context_status(
    conv_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _load_owned_conversation(session, conv_id, user.id)
    llm_cfg = resolve_user_llm(user)
    return await _build_context_status(
        session, conv, context_window=llm_cfg.context_window if llm_cfg else None
    )


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
    if "llm_model" in fields_set:
        conv.llm_model = normalize_model_name(req.llm_model)

    await session.commit()
    await session.refresh(conv)
    return conv.to_summary_dict()


@router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
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
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await _load_owned_conversation(session, conv_id, user.id)

    msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        role=req.role,
        content=req.content or "",
        tool_call_log=json.dumps(req.tools, ensure_ascii=False) if req.tools else None,
        cost_usd=req.cost_usd,
        error=req.error or None,
    )
    session.add(msg)

    if req.role == "user":
        await store_user_memories(
            session,
            user_id=user.id,
            message_id=msg.id,
            content=req.content or "",
            kb_id=conv.kb_id,
            embedding_cfg=resolve_user_embedding(user),
        )
        if _is_default_title(conv.title) and req.content.strip():
            conv.title = _derive_title(req.content)

    conv.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(msg)
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
