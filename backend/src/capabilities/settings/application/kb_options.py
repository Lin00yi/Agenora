"""Embedding, reranker and KB-mode settings use cases."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.capabilities.knowledge.application import configured_vector_size
from src.infra.crypto import encrypt
from src.kb.models import KB


class KBOptionsUseCaseError(ValueError):
    def __init__(self, detail: Any, status_code: int) -> None:
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


async def _affected_kbs(session: Any, *, user_id: str, vector_size: int) -> list[dict[str, Any]]:
    rows = (await session.execute(select(KB).where(KB.user_id == user_id, KB.is_system.is_(False)))).scalars().all()
    return [
        {"id": kb.id, "name": kb.name, "vector_size": kb.vector_size}
        for kb in rows
        if kb.vector_size != vector_size and not getattr(kb, "embedding_provider", None)
    ]


async def save_embedding(session: Any, *, user: Any, body: Any) -> Any:
    affected = await _affected_kbs(session, user_id=user.id, vector_size=body.dim)
    if affected:
        raise KBOptionsUseCaseError({
            "code": "embedding_dim_conflict",
            "message": f"切换到 {body.dim} 维 embedding 会让你已有的 {len(affected)} 个 KB（未单独配置 embedding 的）失效。请先为这些 KB 单独配置 embedding，或删除它们。",
            "new_dim": body.dim, "affected_kbs": affected,
        }, 409)
    user.embedding_provider = body.provider
    user.embedding_base_url = body.base_url.rstrip("/")
    if body.api_key:
        user.embedding_api_key_enc = encrypt(body.api_key)
    elif not user.embedding_api_key_enc and body.provider != "ollama":
        raise KBOptionsUseCaseError("api_key required for first-time configuration", 400)
    user.embedding_model, user.embedding_dim = body.model, body.dim
    await session.commit()
    await session.refresh(user)
    return user


async def clear_embedding(session: Any, *, user: Any) -> None:
    try:
        env_dim = configured_vector_size()
    except Exception:  # configuration errors must preserve legacy clear behavior
        env_dim = None
    if env_dim:
        affected = await _affected_kbs(session, user_id=user.id, vector_size=env_dim)
        if affected:
            raise KBOptionsUseCaseError({
                "code": "embedding_dim_conflict",
                "message": f"清空配置会回到 env 默认 ({env_dim} 维)，但你已有 {len(affected)} 个 KB（未单独配置 embedding 的）维度不同。请先为这些 KB 单独配置 embedding，或删除它们。",
                "new_dim": env_dim, "affected_kbs": affected,
            }, 409)
    user.embedding_provider = user.embedding_base_url = user.embedding_api_key_enc = None
    user.embedding_model = user.embedding_dim = None
    await session.commit()


async def save_kb_web_search(session: Any, *, user: Any, enabled: bool) -> Any:
    user.kb_web_search_enabled = bool(enabled)
    await session.commit()
    await session.refresh(user)
    return user


async def save_reranker(session: Any, *, user: Any, body: Any) -> Any:
    user.reranker_provider = body.provider
    user.reranker_base_url = body.base_url.rstrip("/")
    if body.api_key:
        user.reranker_api_key_enc = encrypt(body.api_key)
    elif not user.reranker_api_key_enc and body.provider != "openai-compat":
        raise KBOptionsUseCaseError("api_key required for first-time configuration", 400)
    user.reranker_model, user.reranker_enabled = body.model, bool(body.enabled)
    await session.commit()
    await session.refresh(user)
    return user


async def clear_reranker(session: Any, *, user: Any) -> None:
    user.reranker_provider = user.reranker_base_url = user.reranker_api_key_enc = None
    user.reranker_model = None
    user.reranker_enabled = False
    await session.commit()
