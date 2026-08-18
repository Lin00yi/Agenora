"""Auth HTTP routes: POST /register, POST /login, GET /me, PATCH /me,
POST /change-password, DELETE /me (v3-M5)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.auth.middleware import CurrentUser
from src.auth.models import User
from src.auth.password import hash_password, verify_password
from src.auth.tokens import issue_token
from src.infra.database import get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=64)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    # Keep the original field for the frontend while exposing the conventional
    # OAuth-style name used by earlier API clients and integration tests.
    access_token: str
    user: dict


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, session: AsyncSession = Depends(get_session)) -> AuthResponse:
    # Check for existing email
    existing = await session.execute(select(User).where(User.email == req.email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    user = User(
        id=str(uuid.uuid4()),
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        display_name=req.display_name or req.email.split("@")[0],
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    token = issue_token(user.id, user.email)
    return AuthResponse(token=token, access_token=token, user=user.to_public_dict())


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)) -> AuthResponse:
    result = await session.execute(select(User).where(User.email == req.email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        # Same error for "no such user" vs "wrong password" to avoid enumeration.
        raise HTTPException(status_code=401, detail="invalid email or password")

    # 06-01 admin-dashboard: banned accounts can authenticate-by-password but
    # must not receive a token. Distinct 403 so the UI can show a clear message.
    if not user.is_active:
        raise HTTPException(status_code=403, detail="account disabled")

    token = issue_token(user.id, user.email)
    return AuthResponse(token=token, access_token=token, user=user.to_public_dict())


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return user.to_public_dict()


# ---------------------------------------------------------------------------
# v3-M5: profile editing
# ---------------------------------------------------------------------------
class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)


@router.patch("/me")
async def update_me(
    req: UpdateProfileRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    u = await session.get(User, user.id)
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    u.display_name = req.display_name.strip()
    await session.commit()
    await session.refresh(u)
    return u.to_public_dict()


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    u = await session.get(User, user.id)
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    if not verify_password(req.old_password, u.password_hash):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    u.password_hash = hash_password(req.new_password)
    await session.commit()
    return {"ok": True}


async def purge_user(session: AsyncSession, user: User) -> None:
    """Hard-delete all user-owned data across relational and external stores.

    User/KB relationships are deliberately soft FKs because deleting a KB
    requires vector, graph, and file cleanup.  This operation therefore first
    calls the explicit KB purge per owned KB.  Each external deletion is
    idempotent; if a provider is temporarily unavailable, the user row and
    remaining metadata stay in place and the same DELETE can be retried.
    """
    from src.conversations.models import Conversation, ConversationSummary, Message, UserMemory
    from src.kb.models import KB, KBInvitation, KBMember
    from src.kb.routes import purge_kb
    from src.observability.models import Observation, Trace
    from src.settings_user.models import LLMConnection, LLMModelProfile

    user_id = user.id
    try:
        owned_kbs = list(
            (await session.execute(select(KB).where(KB.user_id == user_id))).scalars()
        )
        for kb in owned_kbs:
            await purge_kb(session, kb)

        conversation_ids = select(Conversation.id).where(Conversation.user_id == user_id)
        trace_ids = select(Trace.id).where(Trace.user_id == user_id)
        # Explicit child deletes keep the cleanup correct on SQLite deployments
        # where foreign-key enforcement may not be enabled for every connection.
        await session.execute(
            delete(ConversationSummary).where(
                ConversationSummary.conversation_id.in_(conversation_ids)
            )
        )
        await session.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
        await session.execute(delete(Conversation).where(Conversation.user_id == user_id))
        await session.execute(delete(Observation).where(Observation.trace_id.in_(trace_ids)))
        await session.execute(delete(Trace).where(Trace.user_id == user_id))
        await session.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
        await session.execute(delete(LLMModelProfile).where(LLMModelProfile.user_id == user_id))
        await session.execute(delete(LLMConnection).where(LLMConnection.user_id == user_id))
        # Remove the user as a collaborator or invitation creator on KBs owned
        # by other accounts too; those rows otherwise retain a deleted identity.
        await session.execute(delete(KBMember).where(KBMember.user_id == user_id))
        await session.execute(delete(KBInvitation).where(KBInvitation.created_by == user_id))
        await session.delete(user)
        await session.commit()
        log.info("user_purge_completed", user_id=user_id, owned_kb_count=len(owned_kbs))
    except Exception:
        await session.rollback()
        log.exception("user_purge_failed", user_id=user_id)
        raise


@router.delete("/me")
async def delete_me(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Hard-delete the current user (plus the KBs / conversations they own)."""
    u = await session.get(User, user.id)
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    await purge_user(session, u)
    return {"ok": True}
