"""LLM connection lifecycle use cases."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from src.infra.crypto import encrypt
from src.settings_user.models import LLMConnection, LLMModelProfile


class ConnectionUseCaseError(ValueError):
    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.status_code = status_code


async def create(session: Any, *, user_id: str, display_name: str, provider: str, base_url: str, api_key: str, enabled: bool) -> LLMConnection:
    if not api_key.strip():
        raise ConnectionUseCaseError("新增连接需要 API Key。", 400)
    connection = LLMConnection(
        id=str(uuid.uuid4()), user_id=user_id, display_name=display_name.strip(),
        provider=provider, base_url=base_url.rstrip("/"), api_key_enc=encrypt(api_key.strip()), enabled=enabled,
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection


async def update(session: Any, *, connection_id: str, user_id: str, display_name: str, provider: str, base_url: str, api_key: str, enabled: bool) -> LLMConnection:
    connection = await session.get(LLMConnection, connection_id)
    if connection is None or connection.user_id != user_id:
        raise ConnectionUseCaseError("llm connection not found", 404)
    if connection.is_legacy_default:
        raise ConnectionUseCaseError("默认连接请在基础连接配置中编辑。", 409)
    connection.display_name = display_name.strip()
    connection.provider = provider
    connection.base_url = base_url.rstrip("/")
    connection.enabled = enabled
    if api_key.strip():
        connection.api_key_enc = encrypt(api_key.strip())
    await session.commit()
    await session.refresh(connection)
    return connection


async def delete(session: Any, *, connection_id: str, user_id: str) -> None:
    connection = await session.get(LLMConnection, connection_id)
    if connection is None or connection.user_id != user_id:
        raise ConnectionUseCaseError("llm connection not found", 404)
    if connection.is_legacy_default:
        raise ConnectionUseCaseError("默认连接不能删除，请清空基础连接配置。", 409)
    linked = await session.scalar(select(LLMModelProfile.id).where(LLMModelProfile.connection_id == connection.id).limit(1))
    if linked:
        raise ConnectionUseCaseError("该连接仍有关联模型，请先移除或迁移模型。", 409)
    await session.delete(connection)
    await session.commit()


async def load_probeable(session: Any, *, connection_id: str, user_id: str) -> LLMConnection:
    connection = await session.get(LLMConnection, connection_id)
    if connection is None or connection.user_id != user_id:
        raise ConnectionUseCaseError("llm connection not found", 404)
    if not connection.enabled:
        raise ConnectionUseCaseError("该服务连接已停用。", 422)
    if not connection.api_key_enc:
        raise ConnectionUseCaseError("该服务连接没有可用的 API Key。", 422)
    return connection
