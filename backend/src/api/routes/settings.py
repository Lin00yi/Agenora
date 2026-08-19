"""Per-user settings HTTP routes (v2-M1).

Endpoints (all require Bearer JWT):
  GET    /api/settings/me                    — current user's saved + effective config
  PUT    /api/settings/llm                   — save LLM block
  DELETE /api/settings/llm                   — clear LLM block (revert to env fallback)
  PUT    /api/settings/embedding             — save embedding block (with dim-conflict check)
  DELETE /api/settings/embedding             — clear embedding block
  POST   /api/settings/probe/llm             — probe a candidate provider's model list
  POST   /api/settings/probe/embedding       — same for embedding (+ optional live dim probe)

Saving the LLM block with `api_key=""` keeps the existing encrypted key (lets
users update only the model without re-entering the key). Saving the embedding
block follows the same convention.

Dim-conflict semantics: when a user changes their embedding dim while owning
KBs created with a different dim, the PUT returns 409 + `affected_kbs` list.
The user must delete those KBs (or accept the loss) before the change can land.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.middleware import CurrentUser
from src.auth.models import User
from src.conversations.models import Conversation
from src.context import resolve_context_window
from src.infra.crypto import decrypt, encrypt
from src.storage.database import get_session
from src.models.gateway import normalize_model_name
from src.models.catalog import resolve_model_catalog_entry
from src.kb.models import KB
from src.settings_user.models import (LLMConnection, LLMModelProfile,
                                      ensure_legacy_llm_connection,
                                      ensure_legacy_llm_model_profiles,
                                      list_llm_connections,
                                      list_llm_model_profiles)
from src.settings_user.probe import (EmbeddingProbeResult, ProbeError,
                                     probe_embedding, probe_llm_models)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
LLM_PROVIDERS = Literal["anthropic", "openai-compat"]
EMBEDDING_PROVIDERS = Literal["openai-compat", "ollama"]
RERANKER_PROVIDERS = Literal["siliconflow", "cohere", "openai-compat"]


class LLMBody(BaseModel):
    provider: LLM_PROVIDERS
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=512)  # "" = keep existing
    # Required only for the first configuration. Once a model catalog exists,
    # the routing policy owns the active profile and a connection edit should
    # not silently replace it.
    default_model: str | None = Field(default=None, max_length=128)
    # Omitted means "leave automatic routing unchanged".  This lets the
    # default connection be edited independently from the routing policy.
    complex_model: str | None = Field(default=None, max_length=128)
    # None is the default for new configurations: resolve well-known model IDs
    # in the server registry. A number is an explicit BYOK override.
    context_window: int | None = Field(default=None, ge=4_096, le=2_000_000)


class LLMModelProfileBody(BaseModel):
    connection_id: str | None = Field(default=None, max_length=36)
    display_name: str = Field(min_length=1, max_length=96)
    model_id: str = Field(min_length=1, max_length=128)
    context_window: int | None = Field(default=None, ge=4_096, le=2_000_000)
    # Optional complete override for the actual connection price, in USD per
    # million tokens. This is needed for resellers and private proxies whose
    # billing differs from a model's vendor price in models.dev.
    input_price_per_million: float | None = Field(default=None, ge=0, le=100_000)
    output_price_per_million: float | None = Field(default=None, ge=0, le=100_000)
    cache_read_price_per_million: float | None = Field(default=None, ge=0, le=100_000)
    cache_write_price_per_million: float | None = Field(default=None, ge=0, le=100_000)
    enabled: bool = True
    supports_tools: bool = True


class LLMConnectionBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=96)
    provider: LLM_PROVIDERS
    base_url: str = Field(min_length=1, max_length=255)
    # Empty key keeps the existing encrypted secret on PATCH only.
    api_key: str = Field(default="", max_length=512)
    enabled: bool = True


class LLMModelPolicyBody(BaseModel):
    default_profile_id: str = Field(min_length=1, max_length=36)
    complex_enabled: bool = False
    complex_profile_id: str | None = Field(default=None, max_length=36)
    triage_profile_id: str | None = Field(default=None, max_length=36)
    fallback_profile_id: str | None = Field(default=None, max_length=36)


class DeleteLLMModelProfileBody(BaseModel):
    """Optional replacement used to preserve historical conversation choices."""

    replacement_profile_id: str | None = Field(default=None, max_length=36)


class EmbeddingBody(BaseModel):
    provider: EMBEDDING_PROVIDERS
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=512)
    model: str = Field(min_length=1, max_length=128)
    dim: int = Field(gt=0, le=8192)


class RerankerBody(BaseModel):
    """v3-M4: per-user cross-encoder reranker config (opt-in, default off)."""
    provider: RERANKER_PROVIDERS
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=512)  # "" = keep existing
    model: str = Field(min_length=1, max_length=128)
    enabled: bool = True


class ProbeLLMBody(BaseModel):
    provider: LLM_PROVIDERS
    base_url: str = Field(min_length=1, max_length=255)
    # Empty means "reuse the key already saved for this exact provider + URL".
    # The route below deliberately rejects an empty value for any other target.
    api_key: str = Field(default="", max_length=512)


class ProbeEmbeddingBody(BaseModel):
    provider: EMBEDDING_PROVIDERS
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=512)
    model: str = Field(default="", max_length=128)


class ProbeRerankerBody(BaseModel):
    """v3-M4: probe a candidate reranker provider — reuses the openai-compat
    /models lister so the UI dropdown can be populated. The list is unfiltered;
    the user picks the rerank-capable model name themselves.
    """
    provider: RERANKER_PROVIDERS
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(default="", max_length=512)


class KbOptionsBody(BaseModel):
    """v2-M6: per-user KB-mode toggles. Currently just web_search opt-in."""
    kb_web_search_enabled: bool


# ---------------------------------------------------------------------------
# GET /me — current saved + effective view
# ---------------------------------------------------------------------------
def _profile_to_public(profile: LLMModelProfile) -> dict:
    """Expose the resolved automatic window without turning it into an override."""
    context = resolve_context_window(profile.model_id, profile.context_window)
    return {
        **profile.to_public_dict(),
        "context_window_resolved": context.value,
        "context_window_source": context.source,
        "catalog": (
            entry.to_public_dict()
            if (entry := resolve_model_catalog_entry(profile.model_id))
            else None
        ),
    }


def _validate_profile_pricing(body: LLMModelProfileBody) -> None:
    if (body.input_price_per_million is None) != (body.output_price_per_million is None):
        raise HTTPException(
            status_code=422,
            detail="自定义价格必须同时填写输入和输出单价。",
        )
    if (
        body.input_price_per_million is None
        and (body.cache_read_price_per_million is not None or body.cache_write_price_per_million is not None)
    ):
        raise HTTPException(
            status_code=422,
            detail="缓存价格只能与输入、输出自定义价格一起填写。",
        )


def _to_public(
    user: User,
    profiles: list[LLMModelProfile] | None = None,
    connections: list[LLMConnection] | None = None,
) -> dict:
    """Saved-side projection (user's persisted choices). Never reveal api_key."""
    from src.settings import get_settings

    s = get_settings()
    legacy_llm_configured = bool(
        user.llm_provider
        and user.llm_base_url
        and user.llm_api_key_enc
        and user.llm_default_model
    )
    profiles_by_id = {profile.id: profile for profile in profiles or []}
    connections_by_id = {connection.id: connection for connection in connections or []}
    primary_profile = profiles_by_id.get(getattr(user, "llm_default_profile_id", None))
    primary_connection = (
        connections_by_id.get(primary_profile.connection_id)
        if primary_profile and primary_profile.connection_id
        else None
    )
    profile_llm_configured = bool(
        primary_profile
        and primary_profile.enabled
        and primary_connection
        and primary_connection.enabled
        and primary_connection.api_key_enc
    )
    # A selected profile is a complete runtime configuration in its own right;
    # it does not need to duplicate credentials into the legacy User columns.
    user_llm_configured = legacy_llm_configured or profile_llm_configured
    system_llm_base_url = (
        s.deepseek_base_url if s.llm_provider == "deepseek" else s.anthropic_base_url
    )
    system_llm_has_key = bool(
        s.deepseek_api_key if s.llm_provider == "deepseek" else s.anthropic_api_key
    )
    system_llm_configured = bool(system_llm_base_url and system_llm_has_key and s.llm_default_model)
    effective_llm_source = (
        "user"
        if user_llm_configured
        else "system"
        if (not s.byok_required and system_llm_configured)
        else "missing"
    )
    saved_default_model = normalize_model_name(
        primary_profile.model_id if profile_llm_configured and primary_profile else user.llm_default_model
    )
    saved_context_override = (
        primary_profile.context_window
        if profile_llm_configured and primary_profile
        else getattr(user, "llm_context_window", None)
    )
    saved_context = (
        resolve_context_window(saved_default_model, saved_context_override)
        if saved_default_model
        else None
    )
    effective_model = (
        saved_default_model
        if user_llm_configured
        else normalize_model_name(s.llm_default_model)
        if effective_llm_source == "system"
        else None
    )
    effective_context = (
        resolve_context_window(
            effective_model,
            saved_context_override if effective_llm_source == "user" else None,
        )
        if effective_model
        else None
    )

    return {
        "llm": {
            "provider": user.llm_provider,
            "base_url": user.llm_base_url,
            "default_model": saved_default_model,
            "complex_model": normalize_model_name(user.llm_complex_model),
            "context_window": saved_context_override,
            "context_window_resolved": saved_context.value if saved_context else None,
            "context_window_source": saved_context.source if saved_context else None,
            "has_key": bool(
                user.llm_api_key_enc
                or (primary_connection and primary_connection.api_key_enc)
            ),
            "configured": user_llm_configured,
            "effective_configured": effective_llm_source != "missing",
            "effective_source": effective_llm_source,
            "effective_model": effective_model,
            "effective_complex_model": (
                normalize_model_name(user.llm_complex_model or user.llm_default_model)
                if user_llm_configured
                else normalize_model_name(s.llm_complex_model or s.llm_default_model)
                if effective_llm_source == "system"
                else None
            ),
            "effective_context_window": effective_context.value if effective_context else None,
            "effective_context_window_source": effective_context.source if effective_context else None,
            "complex_enabled": bool(getattr(user, "llm_complex_enabled", False)),
            "default_profile_id": getattr(user, "llm_default_profile_id", None),
            "complex_profile_id": getattr(user, "llm_complex_profile_id", None),
            "triage_profile_id": getattr(user, "llm_triage_profile_id", None),
            "fallback_profile_id": getattr(user, "llm_fallback_profile_id", None),
            "triage_model": normalize_model_name(getattr(user, "llm_triage_model", None)),
            "fallback_model": normalize_model_name(getattr(user, "llm_fallback_model", None)),
            "model_profiles": [_profile_to_public(profile) for profile in profiles or []],
            "connections": [connection.to_public_dict() for connection in connections or []],
        },
        "embedding": {
            "provider": user.embedding_provider,
            "base_url": user.embedding_base_url,
            "model": user.embedding_model,
            "dim": user.embedding_dim,
            "has_key": bool(user.embedding_api_key_enc),
            "configured": bool(
                user.embedding_provider
                and user.embedding_base_url
                and user.embedding_model
                and user.embedding_dim
            ),
        },
        # v3-M4: per-user cross-encoder reranker. `configured` = config fields
        # present; `enabled` = toggle on. Resolver requires both for the
        # reranker to actually fire at chat time.
        "reranker": {
            "provider": getattr(user, "reranker_provider", None),
            "base_url": getattr(user, "reranker_base_url", None),
            "model": getattr(user, "reranker_model", None),
            "has_key": bool(getattr(user, "reranker_api_key_enc", None)),
            "configured": bool(
                getattr(user, "reranker_provider", None)
                and getattr(user, "reranker_base_url", None)
                and getattr(user, "reranker_model", None)
            ),
            "enabled": bool(getattr(user, "reranker_enabled", False)),
        },
        # v2-M6: KB-mode toggles.
        "kb_options": {
            "kb_web_search_enabled": bool(getattr(user, "kb_web_search_enabled", False)),
        },
    }


@router.get("/me")
async def get_my_settings(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    profiles = await ensure_legacy_llm_model_profiles(session, user)
    connections = await list_llm_connections(session, user_id=user.id)
    await session.commit()
    return _to_public(user, profiles, connections)


# ---------------------------------------------------------------------------
# PUT /llm — save LLM block
# ---------------------------------------------------------------------------
@router.put("/llm")
async def save_llm(
    body: LLMBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_row = await session.get(User, user.id)
    if user_row is None:
        raise HTTPException(status_code=404, detail="user not found")

    user_row.llm_provider = body.provider
    user_row.llm_base_url = body.base_url.rstrip("/")
    if body.api_key:
        user_row.llm_api_key_enc = encrypt(body.api_key)
    elif not user_row.llm_api_key_enc:
        raise HTTPException(
            status_code=400, detail="api_key required for first-time configuration"
        )
    requested_default_model = normalize_model_name(body.default_model or "")
    if requested_default_model:
        user_row.llm_default_model = requested_default_model
    elif not user_row.llm_default_model:
        raise HTTPException(
            status_code=400, detail="default_model required for first-time configuration"
        )
    if body.complex_model is not None:
        user_row.llm_complex_model = normalize_model_name(
            body.complex_model or user_row.llm_default_model
        )
        user_row.llm_complex_enabled = bool(
            body.complex_model.strip()
            and body.complex_model.strip() != user_row.llm_default_model
        )
    elif not user_row.llm_complex_model:
        user_row.llm_complex_model = user_row.llm_default_model
        user_row.llm_complex_enabled = False
    user_row.llm_context_window = body.context_window
    profiles = await ensure_legacy_llm_model_profiles(session, user_row)
    connections = await list_llm_connections(session, user_id=user.id)
    for profile in profiles:
        if (
            profile.model_id == user_row.llm_default_model
            and not user_row.llm_default_profile_id
        ):
            profile.context_window = body.context_window
            user_row.llm_default_profile_id = profile.id
        if (
            profile.model_id == user_row.llm_complex_model
            and not user_row.llm_complex_profile_id
        ):
            user_row.llm_complex_profile_id = profile.id
    await session.commit()
    await session.refresh(user_row)
    return _to_public(user_row, profiles, connections)


@router.delete("/llm", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def clear_llm(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    user_row = await session.get(User, user.id)
    if user_row is None:
        return
    user_row.llm_provider = None
    user_row.llm_base_url = None
    user_row.llm_api_key_enc = None
    user_row.llm_default_model = None
    user_row.llm_complex_model = None
    user_row.llm_context_window = None
    user_row.llm_complex_enabled = False
    user_row.llm_triage_model = None
    user_row.llm_fallback_model = None
    user_row.llm_default_profile_id = None
    user_row.llm_complex_profile_id = None
    user_row.llm_triage_profile_id = None
    user_row.llm_fallback_profile_id = None
    await session.commit()


async def _owned_llm_profiles(
    session: AsyncSession,
    *,
    user_id: str,
    include_disabled: bool = True,
) -> list[LLMModelProfile]:
    return await list_llm_model_profiles(
        session, user_id=user_id, include_disabled=include_disabled
    )


async def _owned_llm_connections(
    session: AsyncSession,
    *,
    user_id: str,
    include_disabled: bool = True,
) -> list[LLMConnection]:
    return await list_llm_connections(
        session, user_id=user_id, include_disabled=include_disabled
    )


@router.post("/llm/connections", status_code=status.HTTP_201_CREATED)
async def create_llm_connection(
    body: LLMConnectionBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not body.api_key.strip():
        raise HTTPException(status_code=400, detail="新增连接需要 API Key。")
    connection = LLMConnection(
        id=str(uuid.uuid4()),
        user_id=user.id,
        display_name=body.display_name.strip(),
        provider=body.provider,
        base_url=body.base_url.rstrip("/"),
        api_key_enc=encrypt(body.api_key.strip()),
        enabled=body.enabled,
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection.to_public_dict()


@router.patch("/llm/connections/{connection_id}")
async def update_llm_connection(
    connection_id: str,
    body: LLMConnectionBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    connection = await session.get(LLMConnection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(status_code=404, detail="llm connection not found")
    if connection.is_legacy_default:
        raise HTTPException(status_code=409, detail="默认连接请在基础连接配置中编辑。")
    connection.display_name = body.display_name.strip()
    connection.provider = body.provider
    connection.base_url = body.base_url.rstrip("/")
    connection.enabled = body.enabled
    if body.api_key.strip():
        connection.api_key_enc = encrypt(body.api_key.strip())
    await session.commit()
    await session.refresh(connection)
    return connection.to_public_dict()


@router.delete("/llm/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_llm_connection(
    connection_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    connection = await session.get(LLMConnection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(status_code=404, detail="llm connection not found")
    if connection.is_legacy_default:
        raise HTTPException(status_code=409, detail="默认连接不能删除，请清空基础连接配置。")
    linked = await session.scalar(
        select(LLMModelProfile.id).where(LLMModelProfile.connection_id == connection.id).limit(1)
    )
    if linked:
        raise HTTPException(status_code=409, detail="该连接仍有关联模型，请先移除或迁移模型。")
    await session.delete(connection)
    await session.commit()


@router.post("/llm/connections/{connection_id}/probe")
async def probe_saved_llm_connection(
    connection_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Discover models through a saved connection without exposing its secret."""
    connection = await session.get(LLMConnection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(status_code=404, detail="llm connection not found")
    if not connection.enabled:
        raise HTTPException(status_code=422, detail="该服务连接已停用。")
    if not connection.api_key_enc:
        raise HTTPException(status_code=422, detail="该服务连接没有可用的 API Key。")
    try:
        models = await probe_llm_models(
            connection.provider,
            connection.base_url,
            decrypt(connection.api_key_enc),
        )
    except ProbeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "models": models,
        "context_windows": {
            model: {
                "value": resolution.value,
                "source": resolution.source,
            }
            for model in models
            if (resolution := resolve_context_window(model)).source == "models.dev"
        },
    }


@router.post("/llm/models", status_code=status.HTTP_201_CREATED)
async def create_llm_model_profile(
    body: LLMModelProfileBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Register an arbitrary chat model under the user's validated connection."""
    _validate_profile_pricing(body)
    await ensure_legacy_llm_connection(session, user)
    connections = await _owned_llm_connections(session, user_id=user.id)
    connection_id = body.connection_id
    if connection_id is None:
        connection_id = next((item.id for item in connections if item.is_legacy_default), None)
    connection = next((item for item in connections if item.id == connection_id and item.enabled), None)
    if connection is None:
        raise HTTPException(status_code=422, detail="请选择一个已启用的模型连接。")
    model_id = normalize_model_name(body.model_id) or ""
    profiles = await _owned_llm_profiles(session, user_id=user.id)
    if any(profile.model_id == model_id and profile.connection_id == connection.id for profile in profiles):
        raise HTTPException(status_code=409, detail="该模型已经在可用模型列表中。")
    profile = LLMModelProfile(
        id=str(uuid.uuid4()),
        user_id=user.id,
        connection_id=connection.id,
        display_name=body.display_name.strip(),
        model_id=model_id,
        context_window=body.context_window,
        input_price_per_million=body.input_price_per_million,
        output_price_per_million=body.output_price_per_million,
        cache_read_price_per_million=body.cache_read_price_per_million,
        cache_write_price_per_million=body.cache_write_price_per_million,
        enabled=body.enabled,
        supports_tools=body.supports_tools,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return _profile_to_public(profile)


@router.patch("/llm/models/{profile_id}")
async def update_llm_model_profile(
    profile_id: str,
    body: LLMModelProfileBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    profile = await session.get(LLMModelProfile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=404, detail="model profile not found")
    _validate_profile_pricing(body)
    next_model_id = normalize_model_name(body.model_id) or ""
    connections = await _owned_llm_connections(session, user_id=user.id)
    connection_id = body.connection_id or profile.connection_id
    connection = next((item for item in connections if item.id == connection_id and item.enabled), None)
    if connection is None:
        raise HTTPException(status_code=422, detail="请选择一个已启用的模型连接。")
    profiles = await _owned_llm_profiles(session, user_id=user.id)
    if any(
        item.id != profile.id
        and item.model_id == next_model_id
        and item.connection_id == connection.id
        for item in profiles
    ):
        raise HTTPException(status_code=409, detail="该模型已经在可用模型列表中。")
    profile.display_name = body.display_name.strip()
    profile.connection_id = connection.id
    profile.model_id = next_model_id
    profile.context_window = body.context_window
    profile.input_price_per_million = body.input_price_per_million
    profile.output_price_per_million = body.output_price_per_million
    profile.cache_read_price_per_million = body.cache_read_price_per_million
    profile.cache_write_price_per_million = body.cache_write_price_per_million
    profile.enabled = body.enabled
    profile.supports_tools = body.supports_tools
    await session.commit()
    await session.refresh(profile)
    return _profile_to_public(profile)


@router.delete("/llm/models/{profile_id}")
async def delete_llm_model_profile(
    profile_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    body: DeleteLLMModelProfileBody | None = None,
) -> dict:
    profile = await session.get(LLMModelProfile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=404, detail="model profile not found")
    protected = {
        getattr(user, "llm_default_profile_id", None),
        getattr(user, "llm_complex_profile_id", None) if getattr(user, "llm_complex_enabled", False) else None,
        getattr(user, "llm_triage_profile_id", None),
        getattr(user, "llm_fallback_profile_id", None),
    }
    if profile.id in protected:
        raise HTTPException(status_code=409, detail="该模型正在被路由策略使用，请先调整策略。")

    conversation_count = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.user_id == user.id,
            Conversation.llm_profile_id == profile.id,
        )
    )
    conversation_count = int(conversation_count or 0)
    replacement_id = body.replacement_profile_id if body is not None else None
    if conversation_count and not replacement_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "model_profile_in_use",
                "conversation_count": conversation_count,
                "message": f"该模型仍被 {conversation_count} 个历史会话使用，请选择替代模型后再移除。",
            },
        )
    if replacement_id:
        if replacement_id == profile.id:
            raise HTTPException(status_code=422, detail="替代模型不能与待移除模型相同。")
        replacement = await session.get(LLMModelProfile, replacement_id)
        if (
            replacement is None
            or replacement.user_id != user.id
            or not replacement.enabled
        ):
            raise HTTPException(status_code=422, detail="替代模型不可用，请选择一个已启用的模型。")
        if conversation_count:
            await session.execute(
                update(Conversation)
                .where(
                    Conversation.user_id == user.id,
                    Conversation.llm_profile_id == profile.id,
                )
                .values(
                    llm_profile_id=replacement.id,
                    llm_model=replacement.model_id,
                )
            )
    await session.delete(profile)
    await session.commit()
    return {"migrated_conversations": conversation_count}


@router.put("/llm/policy")
async def save_llm_model_policy(
    body: LLMModelPolicyBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_row = await session.get(User, user.id)
    if user_row is None:
        raise HTTPException(status_code=404, detail="user not found")
    profiles = await _owned_llm_profiles(session, user_id=user.id, include_disabled=False)
    allowed = {profile.id: profile for profile in profiles}
    requested = [
        body.default_profile_id,
        body.complex_profile_id if body.complex_enabled else None,
        body.triage_profile_id,
        body.fallback_profile_id,
    ]
    if any(profile_id and profile_id not in allowed for profile_id in requested):
        raise HTTPException(status_code=422, detail="路由策略只能使用已启用的模型档案。")

    primary = allowed[body.default_profile_id]
    complex_profile = allowed.get(body.complex_profile_id or "")
    triage_profile = allowed.get(body.triage_profile_id or "")
    fallback_profile = allowed.get(body.fallback_profile_id or "")
    user_row.llm_default_profile_id = primary.id
    user_row.llm_default_model = primary.model_id
    user_row.llm_complex_enabled = body.complex_enabled
    user_row.llm_complex_profile_id = complex_profile.id if body.complex_enabled and complex_profile else primary.id
    user_row.llm_complex_model = (complex_profile or primary).model_id
    user_row.llm_triage_profile_id = triage_profile.id if triage_profile else None
    user_row.llm_triage_model = triage_profile.model_id if triage_profile else None
    user_row.llm_fallback_profile_id = fallback_profile.id if fallback_profile else None
    user_row.llm_fallback_model = fallback_profile.model_id if fallback_profile else None
    # Keep old callers and the effective-config header accurate while the
    # runtime itself reads the profile-level mapping.
    user_row.llm_context_window = primary.context_window
    await session.commit()
    await session.refresh(user_row)
    connections = await _owned_llm_connections(session, user_id=user.id)
    return _to_public(user_row, profiles, connections)


# ---------------------------------------------------------------------------
# PUT /embedding — save embedding block (with dim-conflict pre-check)
# ---------------------------------------------------------------------------
@router.put("/embedding")
async def save_embedding(
    body: EmbeddingBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_row = await session.get(User, user.id)
    if user_row is None:
        raise HTTPException(status_code=404, detail="user not found")

    # v3-M7: dim-conflict pre-check now ONLY flags KBs that fall back to the
    # user-level embedding cfg. KBs that carry their own embedding_provider
    # are unaffected by user-cfg changes (they keep using their own creds).
    result = await session.execute(
        select(KB).where(KB.user_id == user.id, KB.is_system.is_(False))
    )
    owned_kbs = result.scalars().all()
    affected = [
        {"id": kb.id, "name": kb.name, "vector_size": kb.vector_size}
        for kb in owned_kbs
        if kb.vector_size != body.dim
        and not getattr(kb, "embedding_provider", None)
    ]
    if affected:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "embedding_dim_conflict",
                "message": (
                    f"切换到 {body.dim} 维 embedding 会让你已有的 {len(affected)} 个 KB（未单独配置 embedding 的）失效。"
                    "请先为这些 KB 单独配置 embedding，或删除它们。"
                ),
                "new_dim": body.dim,
                "affected_kbs": affected,
            },
        )

    user_row.embedding_provider = body.provider
    user_row.embedding_base_url = body.base_url.rstrip("/")
    if body.api_key:
        user_row.embedding_api_key_enc = encrypt(body.api_key)
    elif not user_row.embedding_api_key_enc and body.provider != "ollama":
        raise HTTPException(
            status_code=400, detail="api_key required for first-time configuration"
        )
    user_row.embedding_model = body.model
    user_row.embedding_dim = body.dim
    await session.commit()
    await session.refresh(user_row)
    return _to_public(user_row)


@router.delete("/embedding", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def clear_embedding(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    user_row = await session.get(User, user.id)
    if user_row is None:
        return
    # Same conflict check applies — clearing user cfg means falling back to env dim.
    # If env dim differs from owned KBs, downgrade still corrupts. Block.
    from src.storage.vector.embedding import get_vector_size

    try:
        env_dim = get_vector_size()
    except Exception:
        env_dim = None
    if env_dim:
        result = await session.execute(
            select(KB).where(KB.user_id == user.id, KB.is_system.is_(False))
        )
        affected = [
            {"id": kb.id, "name": kb.name, "vector_size": kb.vector_size}
            for kb in result.scalars().all()
            if kb.vector_size != env_dim
            and not getattr(kb, "embedding_provider", None)
        ]
        if affected:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "embedding_dim_conflict",
                    "message": (
                        f"清空配置会回到 env 默认 ({env_dim} 维)，但你已有 {len(affected)} 个 KB（未单独配置 embedding 的）"
                        "维度不同。请先为这些 KB 单独配置 embedding，或删除它们。"
                    ),
                    "new_dim": env_dim,
                    "affected_kbs": affected,
                },
            )
    user_row.embedding_provider = None
    user_row.embedding_base_url = None
    user_row.embedding_api_key_enc = None
    user_row.embedding_model = None
    user_row.embedding_dim = None
    await session.commit()


# ---------------------------------------------------------------------------
# POST /probe/* — discover what models a candidate config exposes
# ---------------------------------------------------------------------------
@router.post("/probe/llm")
async def probe_llm(
    body: ProbeLLMBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    # v3-M6: when api_key is empty AND provider/base_url match the stored cfg,
    # fall back to the user's saved decrypted key. Lets the frontend re-probe
    # (e.g. on ModelSelect first render) without re-entering credentials.
    api_key = body.api_key
    if not api_key:
        u = await session.get(User, user.id)
        if (
            u is not None
            and u.llm_provider == body.provider
            and (u.llm_base_url or "").rstrip("/") == body.base_url.rstrip("/")
            and u.llm_api_key_enc
        ):
            api_key = decrypt(u.llm_api_key_enc)
    try:
        models = await probe_llm_models(body.provider, body.base_url, api_key)
    except ProbeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "models": models,
        "context_windows": {
            model: {
                "value": resolution.value,
                "source": resolution.source,
            }
            for model in models
            if (resolution := resolve_context_window(model)).source == "models.dev"
        },
    }


@router.post("/probe/embedding")
async def probe_embedding_route(
    body: ProbeEmbeddingBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    # v3-M8: empty api_key + matching provider/base_url → fall back to user's
    # stored decrypted key. Same pattern as probe_llm. Lets the KB creation
    # form re-probe without forcing the user to re-enter creds every time.
    api_key = body.api_key
    if not api_key:
        u = await session.get(User, user.id)
        if (
            u is not None
            and u.embedding_provider == body.provider
            and (u.embedding_base_url or "").rstrip("/") == body.base_url.rstrip("/")
            and u.embedding_api_key_enc
        ):
            api_key = decrypt(u.embedding_api_key_enc)
    try:
        result: EmbeddingProbeResult = await probe_embedding(
            body.provider,
            body.base_url,
            api_key,
            body.model or None,
        )
    except ProbeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"models": result.models, "dim": result.dim}


# ---------------------------------------------------------------------------
# PUT /kb-options — KB-mode toggles (v2-M6)
# ---------------------------------------------------------------------------
@router.put("/kb-options")
async def save_kb_options(
    body: KbOptionsBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_row = await session.get(User, user.id)
    if user_row is None:
        raise HTTPException(status_code=404, detail="user not found")
    user_row.kb_web_search_enabled = bool(body.kb_web_search_enabled)
    await session.commit()
    await session.refresh(user_row)
    return _to_public(user_row)


# ---------------------------------------------------------------------------
# PUT / DELETE / probe /reranker (v3-M4)
# ---------------------------------------------------------------------------
@router.put("/reranker")
async def save_reranker(
    body: RerankerBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Save reranker config block (with optional enable toggle).

    `api_key=""` keeps the existing encrypted key — lets users toggle enable
    or update the model without re-entering the key. First-time configuration
    requires an api_key except for `openai-compat` (self-hosted endpoints may
    not enforce auth).
    """
    user_row = await session.get(User, user.id)
    if user_row is None:
        raise HTTPException(status_code=404, detail="user not found")

    user_row.reranker_provider = body.provider
    user_row.reranker_base_url = body.base_url.rstrip("/")
    if body.api_key:
        user_row.reranker_api_key_enc = encrypt(body.api_key)
    elif not user_row.reranker_api_key_enc and body.provider != "openai-compat":
        raise HTTPException(
            status_code=400, detail="api_key required for first-time configuration"
        )
    user_row.reranker_model = body.model
    user_row.reranker_enabled = bool(body.enabled)
    await session.commit()
    await session.refresh(user_row)
    return _to_public(user_row)


@router.delete("/reranker", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def clear_reranker(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    user_row = await session.get(User, user.id)
    if user_row is None:
        return
    user_row.reranker_provider = None
    user_row.reranker_base_url = None
    user_row.reranker_api_key_enc = None
    user_row.reranker_model = None
    user_row.reranker_enabled = False
    await session.commit()


@router.post("/probe/reranker")
async def probe_reranker(
    body: ProbeRerankerBody,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Probe the candidate provider's model list.

    Reuses the openai-compat /models lister — most rerank providers (SiliconFlow,
    Cohere via /v1/models, self-hosted) expose this. We return the full list
    unfiltered; the UI tells the user to pick a rerank-capable model id (e.g.
    one containing "rerank" or "bge-reranker").

    v3-M8: empty api_key + matching provider/base_url → fall back to user's
    stored decrypted key (same pattern as probe_llm / probe_embedding).
    """
    from src.settings_user.probe import _probe_openai_compat_models

    base_url = (body.base_url or "").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url 不能为空")
    api_key = body.api_key
    if not api_key:
        u = await session.get(User, user.id)
        if (
            u is not None
            and u.reranker_provider == body.provider
            and (u.reranker_base_url or "").rstrip("/") == base_url
            and u.reranker_api_key_enc
        ):
            api_key = decrypt(u.reranker_api_key_enc)
    # Cohere / SiliconFlow / self-hosted all want a Bearer key for /models;
    # openai-compat without a key is theoretically possible (anonymous TEI)
    # but rare — surface a clearer error if the upstream rejects.
    if not api_key and body.provider != "openai-compat":
        raise HTTPException(status_code=400, detail=f"{body.provider}: api_key 不能为空")
    try:
        models = await _probe_openai_compat_models(base_url, api_key)
    except ProbeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"models": models}
