"""LLM model-profile and routing-policy use cases."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update

from src.adapters.llm import normalize_model_name
from src.context import resolve_context_window
from src.conversations.models import Conversation
from src.models.catalog import resolve_model_catalog_entry
from src.settings_user.models import (
    LLMModelProfile,
    ensure_legacy_llm_connection,
    list_llm_connections,
    list_llm_model_profiles,
)


class ModelProfileUseCaseError(ValueError):
    def __init__(self, detail: Any, status_code: int) -> None:
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


def to_public(profile: LLMModelProfile) -> dict[str, Any]:
    context = resolve_context_window(profile.model_id, profile.context_window)
    return {
        **profile.to_public_dict(),
        "context_window_resolved": context.value,
        "context_window_source": context.source,
        "catalog": entry.to_public_dict() if (entry := resolve_model_catalog_entry(profile.model_id)) else None,
    }


def validate_pricing(body: Any) -> None:
    if (body.input_price_per_million is None) != (body.output_price_per_million is None):
        raise ModelProfileUseCaseError("自定义价格必须同时填写输入和输出单价。", 422)
    if body.input_price_per_million is None and (
        body.cache_read_price_per_million is not None or body.cache_write_price_per_million is not None
    ):
        raise ModelProfileUseCaseError("缓存价格只能与输入、输出自定义价格一起填写。", 422)


async def create(session: Any, *, user: Any, body: Any) -> LLMModelProfile:
    validate_pricing(body)
    await ensure_legacy_llm_connection(session, user)
    connections = await list_llm_connections(session, user_id=user.id)
    connection_id = body.connection_id or next((item.id for item in connections if item.is_legacy_default), None)
    connection = next((item for item in connections if item.id == connection_id and item.enabled), None)
    if connection is None:
        raise ModelProfileUseCaseError("请选择一个已启用的模型连接。", 422)
    model_id = normalize_model_name(body.model_id) or ""
    profiles = await list_llm_model_profiles(session, user_id=user.id)
    if any(item.model_id == model_id and item.connection_id == connection.id for item in profiles):
        raise ModelProfileUseCaseError("该模型已经在可用模型列表中。", 409)
    profile = LLMModelProfile(
        id=str(uuid.uuid4()), user_id=user.id, connection_id=connection.id,
        display_name=body.display_name.strip(), model_id=model_id, context_window=body.context_window,
        input_price_per_million=body.input_price_per_million, output_price_per_million=body.output_price_per_million,
        cache_read_price_per_million=body.cache_read_price_per_million,
        cache_write_price_per_million=body.cache_write_price_per_million,
        enabled=body.enabled, supports_tools=body.supports_tools,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def update_profile(session: Any, *, profile_id: str, user_id: str, body: Any) -> LLMModelProfile:
    profile = await session.get(LLMModelProfile, profile_id)
    if profile is None or profile.user_id != user_id:
        raise ModelProfileUseCaseError("model profile not found", 404)
    validate_pricing(body)
    model_id = normalize_model_name(body.model_id) or ""
    connections = await list_llm_connections(session, user_id=user_id)
    connection = next((item for item in connections if item.id == (body.connection_id or profile.connection_id) and item.enabled), None)
    if connection is None:
        raise ModelProfileUseCaseError("请选择一个已启用的模型连接。", 422)
    profiles = await list_llm_model_profiles(session, user_id=user_id)
    if any(item.id != profile.id and item.model_id == model_id and item.connection_id == connection.id for item in profiles):
        raise ModelProfileUseCaseError("该模型已经在可用模型列表中。", 409)
    profile.display_name = body.display_name.strip()
    profile.connection_id = connection.id
    profile.model_id = model_id
    profile.context_window = body.context_window
    profile.input_price_per_million = body.input_price_per_million
    profile.output_price_per_million = body.output_price_per_million
    profile.cache_read_price_per_million = body.cache_read_price_per_million
    profile.cache_write_price_per_million = body.cache_write_price_per_million
    profile.enabled = body.enabled
    profile.supports_tools = body.supports_tools
    await session.commit()
    await session.refresh(profile)
    return profile


async def delete_profile(session: Any, *, profile_id: str, user: Any, replacement_id: str | None) -> int:
    profile = await session.get(LLMModelProfile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise ModelProfileUseCaseError("model profile not found", 404)
    protected = {user.llm_default_profile_id, user.llm_complex_profile_id if user.llm_complex_enabled else None, user.llm_triage_profile_id, user.llm_fallback_profile_id}
    if profile.id in protected:
        raise ModelProfileUseCaseError("该模型正在被路由策略使用，请先调整策略。", 409)
    count = int(await session.scalar(select(func.count()).select_from(Conversation).where(Conversation.user_id == user.id, Conversation.llm_profile_id == profile.id)) or 0)
    if count and not replacement_id:
        raise ModelProfileUseCaseError({"code": "model_profile_in_use", "conversation_count": count, "message": f"该模型仍被 {count} 个历史会话使用，请选择替代模型后再移除。"}, 409)
    if replacement_id:
        if replacement_id == profile.id:
            raise ModelProfileUseCaseError("替代模型不能与待移除模型相同。", 422)
        replacement = await session.get(LLMModelProfile, replacement_id)
        if replacement is None or replacement.user_id != user.id or not replacement.enabled:
            raise ModelProfileUseCaseError("替代模型不可用，请选择一个已启用的模型。", 422)
        if count:
            await session.execute(update(Conversation).where(Conversation.user_id == user.id, Conversation.llm_profile_id == profile.id).values(llm_profile_id=replacement.id, llm_model=replacement.model_id))
    await session.delete(profile)
    await session.commit()
    return count


async def save_policy(session: Any, *, user: Any, body: Any) -> None:
    profiles = await list_llm_model_profiles(session, user_id=user.id, include_disabled=False)
    allowed = {profile.id: profile for profile in profiles}
    requested = [body.default_profile_id, body.complex_profile_id if body.complex_enabled else None, body.triage_profile_id, body.fallback_profile_id]
    if any(profile_id and profile_id not in allowed for profile_id in requested):
        raise ModelProfileUseCaseError("路由策略只能使用已启用的模型档案。", 422)
    primary = allowed[body.default_profile_id]
    complex_profile = allowed.get(body.complex_profile_id or "")
    triage_profile = allowed.get(body.triage_profile_id or "")
    fallback_profile = allowed.get(body.fallback_profile_id or "")
    user.llm_default_profile_id, user.llm_default_model = primary.id, primary.model_id
    user.llm_complex_enabled = body.complex_enabled
    user.llm_complex_profile_id = complex_profile.id if body.complex_enabled and complex_profile else primary.id
    user.llm_complex_model = (complex_profile or primary).model_id
    user.llm_triage_profile_id = triage_profile.id if triage_profile else None
    user.llm_triage_model = triage_profile.model_id if triage_profile else None
    user.llm_fallback_profile_id = fallback_profile.id if fallback_profile else None
    user.llm_fallback_model = fallback_profile.model_id if fallback_profile else None
    user.llm_context_window = primary.context_window
    await session.commit()
    await session.refresh(user)
