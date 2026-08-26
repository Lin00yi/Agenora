"""Embedding, reranker and KB-mode settings use cases."""
from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from src.capabilities.knowledge.application import configured_vector_size
from src.platform.security.crypto import encrypt
from src.capabilities.knowledge.domain.models import KB
from src.capabilities.settings.domain.models import UserWebSearchConfig
from src.harness.tools.search_providers import get_search_provider


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


async def save_web_search(session: Any, *, user: Any, body: Any) -> Any:
    previous_provider = getattr(user, "web_search_provider", None)
    api_key = body.api_key
    if body.provider != "duckduckgo" and not api_key:
        if previous_provider == body.provider and user.web_search_api_key_enc:
            from src.platform.security.crypto import decrypt

            api_key = decrypt(user.web_search_api_key_enc)
        else:
            # A key saved for another engine must never be reused implicitly.
            # It would otherwise cause a confusing authentication failure (or
            # spend a different provider's quota) after the engine is switched.
            raise KBOptionsUseCaseError("api_key required for first-time configuration", 400)

    # This is deliberately before every persistent mutation: an invalid key,
    # unsupported provider, or unreachable network leaves the active engine
    # untouched. Do not replace it with a client-only check.
    await verify_web_search(provider=body.provider, api_key=api_key)

    if body.api_key:
        user.web_search_api_key_enc = encrypt(body.api_key)
    elif body.provider == "duckduckgo":
        # DuckDuckGo never needs a credential; discard an old paid-provider
        # key rather than retaining an unrelated secret indefinitely.
        user.web_search_api_key_enc = None
    user.web_search_provider = body.provider
    await session.commit()
    await session.refresh(user)
    return user


async def verify_web_search(*, provider: str, api_key: str) -> int:
    """Run a minimal real search before accepting an engine configuration."""
    try:
        results = await get_search_provider(
            UserWebSearchConfig(provider=provider, api_key=api_key)
        ).search("Agenora AI agent", max_results=1)
    except httpx.TimeoutException as exc:
        raise KBOptionsUseCaseError(
            {
                "code": "search_provider_timeout",
                "message": "搜索引擎连接超时，请检查网络后重试。",
            },
            504,
        ) from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            detail = {
                "code": "search_provider_auth_failed",
                "message": "API Key 无效，或当前账号没有搜索权限。",
            }
        elif status_code == 429:
            detail = {
                "code": "search_provider_rate_limited",
                "message": "搜索引擎配额已用尽或请求过于频繁，请稍后重试。",
            }
        else:
            detail = {
                "code": "search_provider_rejected",
                "message": f"搜索引擎拒绝了验证请求（HTTP {status_code}）。",
            }
        raise KBOptionsUseCaseError(detail, 502) from exc
    except httpx.RequestError as exc:
        raise KBOptionsUseCaseError(
            {
                "code": "search_provider_unreachable",
                "message": "无法连接搜索引擎，请检查网络、代理或服务状态。",
            },
            502,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - provider adapters may raise SDK errors
        raise KBOptionsUseCaseError(
            {
                "code": "search_provider_verification_failed",
                "message": "搜索引擎验证失败，请检查引擎配置后重试。",
            },
            502,
        ) from exc
    if not results:
        raise KBOptionsUseCaseError(
            {
                "code": "search_provider_empty_result",
                "message": "搜索引擎已响应但未返回可用结果，未保存此配置。",
            },
            422,
        )
    return len(results)


async def verify_system_web_search() -> int:
    """Verify the deployment fallback before removing a user override."""
    try:
        results = await get_search_provider().search("Agenora AI agent", max_results=1)
    except Exception as exc:  # noqa: BLE001 - normalize fallback failures too
        # Keep deployment credentials out of the response while exposing a
        # useful, stable error category to the settings UI.
        if isinstance(exc, httpx.TimeoutException):
            raise KBOptionsUseCaseError(
                {
                    "code": "system_search_provider_timeout",
                    "message": "系统默认搜索引擎连接超时，暂不能恢复默认配置。",
                },
                504,
            ) from exc
        raise KBOptionsUseCaseError(
            {
                "code": "system_search_provider_unavailable",
                "message": "系统默认搜索引擎不可用，暂不能恢复默认配置。",
            },
            502,
        ) from exc
    if not results:
        raise KBOptionsUseCaseError(
            {
                "code": "system_search_provider_empty_result",
                "message": "系统默认搜索引擎未返回可用结果，暂不能恢复默认配置。",
            },
            422,
        )
    return len(results)


async def clear_web_search(session: Any, *, user: Any) -> None:
    user.web_search_provider = None
    user.web_search_api_key_enc = None
    await session.commit()
