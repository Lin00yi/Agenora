"""Knowledge-base membership use cases."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.auth.models import User
from src.kb.models import KBMember


class MemberNotFoundError(LookupError):
    pass


class InvalidMemberOperationError(ValueError):
    pass


async def list_members(session: Any, kb: Any) -> dict[str, Any]:
    members = list(kb.members) if kb.members is not None else []
    ids = {kb.user_id}
    for member in members:
        ids.add(member.user_id)
        if member.invited_by:
            ids.add(member.invited_by)
    rows = (
        await session.execute(
            select(User.id, User.email, User.display_name).where(User.id.in_([item for item in ids if item]))
        )
    ).all()
    info = {
        row.id: {"email": row.email, "display_name": row.display_name or None}
        for row in rows
    }
    owner_info = info.get(kb.user_id)
    owner = {"user_id": kb.user_id, **owner_info} if owner_info and not kb.is_system else None
    out = []
    for member in sorted(members, key=lambda item: item.created_at):
        member_info = info.get(member.user_id, {"email": "(unknown)", "display_name": None})
        inviter = info.get(member.invited_by, {"email": None}) if member.invited_by else {}
        out.append(
            {
                "user_id": member.user_id,
                "email": member_info["email"],
                "display_name": member_info.get("display_name"),
                "role": member.role,
                "invited_by_email": inviter.get("email"),
                "created_at": member.created_at.isoformat() if member.created_at else None,
            }
        )
    return {"owner": owner, "members": out}


async def invite(session: Any, kb: Any, *, email: str, role: str, invited_by: str) -> dict[str, Any]:
    target = (await session.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    if target is None:
        raise MemberNotFoundError("user with that email not found")
    if target.id == kb.user_id:
        raise InvalidMemberOperationError("owner cannot be invited as member")
    existing = (
        await session.execute(
            select(KBMember).where(KBMember.kb_id == kb.id, KBMember.user_id == target.id)
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(KBMember(kb_id=kb.id, user_id=target.id, role=role, invited_by=invited_by))
    else:
        existing.role = role
    await session.commit()
    return {
        "user_id": target.id,
        "email": target.email,
        "display_name": target.display_name or None,
        "role": role,
    }


async def update_role(session: Any, kb_id: str, *, user_id: str, role: str) -> dict[str, Any]:
    member = (
        await session.execute(select(KBMember).where(KBMember.kb_id == kb_id, KBMember.user_id == user_id))
    ).scalar_one_or_none()
    if member is None:
        raise MemberNotFoundError("member not found")
    member.role = role
    await session.commit()
    return member.to_public_dict()


async def remove(session: Any, kb_id: str, *, user_id: str) -> None:
    member = (
        await session.execute(select(KBMember).where(KBMember.kb_id == kb_id, KBMember.user_id == user_id))
    ).scalar_one_or_none()
    if member is None:
        raise MemberNotFoundError("member not found")
    await session.delete(member)
    await session.commit()
