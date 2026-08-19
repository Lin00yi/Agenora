"""User-scoped LLM / embedding config dataclasses + resolution helpers (v2-M1).

`resolve_user_*` returns either:
  - A populated UserXxxConfig dataclass (user has explicitly configured this side)
  - None (user has not configured it → call sites fall back to env via get_settings)

Provider taxonomy (user-facing):
  LLM:        `anthropic` | `openai-compat`
  Embedding:  `openai-compat` | `ollama`

`openai-compat` covers OpenAI, DeepSeek, SiliconFlow, Together, Groq, vLLM,
LMStudio, modern Ollama (/v1 path) — anything with a Bearer-auth `/embeddings`
or `/chat/completions` endpoint.

`ollama` (embedding only) means native protocol POST /api/embeddings — kept as
a distinct provider because (a) no auth and (b) different request/response shape.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.infra.crypto import decrypt
from src.storage.database import Base
from src.settings import get_settings

if TYPE_CHECKING:
    from src.auth.models import User


@dataclass(frozen=True, slots=True)
class UserLLMConfig:
    provider: str          # "anthropic" | "openai-compat"
    base_url: str          # e.g. "https://api.deepseek.com"
    api_key: str           # plaintext (decrypted)
    default_model: str
    complex_model: str     # if user didn't set, mirrors default_model
    context_window: int | None  # optional BYOK override; None uses the registry
    # Routing is opt-in. A manual conversation choice disables this route by
    # replacing both default and complex model for that request.
    complex_enabled: bool = False
    triage_model: str | None = None
    fallback_model: str | None = None
    # Profile-level windows take precedence over the legacy connection-wide
    # override. This keeps a 16K local model from inheriting a 200K cloud-model
    # setting when both live under one BYOK connection.
    model_context_windows: dict[str, int | None] = field(default_factory=dict)
    # User-entered reseller/proxy prices, in USD per 1M tokens. Entries are
    # keyed by model ID and deliberately travel with the selected profile.
    model_pricing_overrides: dict[str, dict[str, float | None]] = field(default_factory=dict)
    # None denotes an environment/legacy config that has no independently
    # managed connection record.  Profile-backed calls set this so health and
    # circuit state can be tracked without ever retaining a plaintext secret.
    connection_id: str | None = None


@dataclass(frozen=True, slots=True)
class UserLLMRoutingConfigs:
    """Resolved provider configs for automatic routing targets.

    Each member may use a different connection.  Call sites must only switch
    to ``fallback`` before client-visible streaming begins.
    """

    primary: UserLLMConfig
    complex: UserLLMConfig | None = None
    triage: UserLLMConfig | None = None
    fallback: UserLLMConfig | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LLMModelProfile(Base):
    """One chat-capable model registered under one user-owned connection."""

    __tablename__ = "llm_model_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # Nullable for rows created by the first model-profile release.  They are
    # attached to a lazily materialised legacy connection on the next request.
    connection_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(96), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    input_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    output_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    cache_read_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    cache_write_price_per_million: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "display_name": self.display_name,
            "model_id": self.model_id,
            "context_window": self.context_window,
            "pricing_override": self.pricing_override(),
            "enabled": self.enabled,
            "supports_tools": self.supports_tools,
        }

    def pricing_override(self) -> dict[str, float | None] | None:
        if self.input_price_per_million is None or self.output_price_per_million is None:
            return None
        return {
            "input": self.input_price_per_million,
            "output": self.output_price_per_million,
            "cache_read": self.cache_read_price_per_million,
            "cache_write": self.cache_write_price_per_million,
        }


class LLMConnection(Base):
    """Encrypted, independently enabled provider connection for one user.

    The original credential fields on ``User`` remain the compatibility
    source-of-truth for the default connection.  New connections are stored
    here, and the public projection intentionally exposes only ``has_key``.
    """

    __tablename__ = "llm_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(96), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    is_legacy_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    circuit_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def to_public_dict(self) -> dict:
        now = _utcnow()
        open_until = self.circuit_open_until
        if open_until is not None and open_until.tzinfo is None:
            open_until = open_until.replace(tzinfo=timezone.utc)
        is_open = bool(open_until and open_until > now)
        return {
            "id": self.id,
            "display_name": self.display_name,
            "provider": self.provider,
            "base_url": self.base_url,
            "has_key": bool(self.api_key_enc),
            "enabled": self.enabled,
            "is_legacy_default": self.is_legacy_default,
            "health": {
                "state": "open" if is_open else "closed",
                "consecutive_failures": self.consecutive_failures,
                "retry_at": open_until.isoformat() if is_open else None,
                "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
                "last_error_category": self.last_error_category,
            },
        }


@dataclass(frozen=True, slots=True)
class UserEmbeddingConfig:
    provider: str          # "openai-compat" | "ollama"
    base_url: str          # e.g. "https://api.siliconflow.cn/v1"
    api_key: str           # plaintext (decrypted; empty for ollama)
    model: str
    dim: int


@dataclass(frozen=True, slots=True)
class UserRerankerConfig:
    """v3-M4: per-user cross-encoder reranker (opt-in, default off).

    Cohere-compatible /rerank endpoint shape (SiliconFlow / Cohere / Jina /
    self-hosted TEI). The presence of this dataclass at a call site means the
    user has both saved a config AND flipped the enable toggle on — see
    `resolve_user_reranker` for the two-gate check.
    """
    provider: str          # "siliconflow" | "cohere" | "openai-compat"
    base_url: str          # e.g. "https://api.siliconflow.cn/v1"
    api_key: str           # plaintext (decrypted; empty for self-hosted)
    model: str


def _llm_is_configured(u: "User") -> bool:
    return bool(
        u.llm_provider
        and u.llm_base_url
        and u.llm_api_key_enc
        and u.llm_default_model
    )


def _embedding_is_configured(u: "User") -> bool:
    return bool(
        u.embedding_provider
        and u.embedding_base_url
        and u.embedding_model
        and u.embedding_dim
    )


def _reranker_is_configured(u: "User") -> bool:
    """Reranker requires BOTH the enable toggle AND a fully populated config.

    api_key is allowed to be empty (for self-hosted openai-compat endpoints
    that don't enforce auth) — we treat presence of provider+base_url+model
    plus the toggle as sufficient.
    """
    if not bool(getattr(u, "reranker_enabled", False)):
        return False
    return bool(
        u.reranker_provider
        and u.reranker_base_url
        and u.reranker_model
    )


def resolve_user_llm(user: "User") -> Optional[UserLLMConfig]:
    """Return user's LLM config, or None to fall back to env."""
    if not _llm_is_configured(user):
        return None
    return UserLLMConfig(
        provider=user.llm_provider or "",
        base_url=(user.llm_base_url or "").rstrip("/"),
        api_key=decrypt(user.llm_api_key_enc or ""),
        default_model=user.llm_default_model or "",
        complex_model=user.llm_complex_model or user.llm_default_model or "",
        context_window=getattr(user, "llm_context_window", None),
        complex_enabled=bool(getattr(user, "llm_complex_enabled", False)),
        triage_model=getattr(user, "llm_triage_model", None) or None,
        fallback_model=getattr(user, "llm_fallback_model", None) or None,
    )


def resolve_system_llm() -> Optional[UserLLMConfig]:
    """Return env-backed LLM config, or None when the platform fallback is incomplete."""
    s = get_settings()
    if s.llm_provider == "deepseek":
        provider = "openai-compat"
        base_url = s.deepseek_base_url
        api_key = s.deepseek_api_key
    else:
        provider = s.llm_provider
        base_url = s.anthropic_base_url
        api_key = s.anthropic_api_key

    if not (provider and base_url and api_key and s.llm_default_model):
        return None

    return UserLLMConfig(
        provider=provider,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        default_model=s.llm_default_model,
        complex_model=s.llm_complex_model or s.llm_default_model,
        context_window=None,
        complex_enabled=bool(s.llm_complex_model and s.llm_complex_model != s.llm_default_model),
    )


async def list_llm_model_profiles(
    session: AsyncSession,
    *,
    user_id: str,
    include_disabled: bool = True,
) -> list[LLMModelProfile]:
    query = select(LLMModelProfile).where(LLMModelProfile.user_id == user_id)
    if not include_disabled:
        query = query.where(LLMModelProfile.enabled.is_(True))
    query = query.order_by(LLMModelProfile.created_at, LLMModelProfile.display_name)
    result = await session.execute(query)
    return list(result.scalars().all())


async def list_llm_connections(
    session: AsyncSession,
    *,
    user_id: str,
    include_disabled: bool = True,
) -> list[LLMConnection]:
    query = select(LLMConnection).where(LLMConnection.user_id == user_id)
    if not include_disabled:
        query = query.where(LLMConnection.enabled.is_(True))
    query = query.order_by(LLMConnection.is_legacy_default.desc(), LLMConnection.created_at)
    result = await session.execute(query)
    return list(result.scalars().all())


async def ensure_legacy_llm_connection(
    session: AsyncSession,
    user: "User",
) -> LLMConnection | None:
    """Mirror the pre-pool credential into an internal default connection.

    No plaintext secret is read during this compatibility migration; the
    existing encrypted blob is copied as-is.  The legacy fields remain intact
    so old clients and environment fallback behaviour do not change.
    """
    cfg = resolve_user_llm(user)
    if cfg is None:
        return None
    existing = await session.scalar(
        select(LLMConnection).where(
            LLMConnection.user_id == user.id,
            LLMConnection.is_legacy_default.is_(True),
        )
    )
    if existing is None:
        existing = LLMConnection(
            id=str(uuid.uuid4()),
            user_id=user.id,
            display_name="默认连接",
            provider=cfg.provider,
            base_url=cfg.base_url,
            api_key_enc=user.llm_api_key_enc or "",
            enabled=True,
            is_legacy_default=True,
        )
        session.add(existing)
        await session.flush()
    else:
        # Saving the original connection later must not leave its mirror stale.
        existing.provider = cfg.provider
        existing.base_url = cfg.base_url
        existing.api_key_enc = user.llm_api_key_enc or ""
        existing.enabled = True
    return existing


async def resolve_llm_profile_config(
    session: AsyncSession,
    *,
    user: "User",
    profile_id: str | None,
) -> tuple[LLMModelProfile, UserLLMConfig] | None:
    """Resolve a selected profile to its own provider credentials and window."""
    if not profile_id:
        return None
    profile = await session.get(LLMModelProfile, profile_id)
    if profile is None or profile.user_id != user.id or not profile.enabled:
        return None
    connection: LLMConnection | None = None
    if profile.connection_id:
        connection = await session.get(LLMConnection, profile.connection_id)
        if connection is None or connection.user_id != user.id or not connection.enabled:
            return None
    else:
        connection = await ensure_legacy_llm_connection(session, user)
        if connection is None:
            return None
        profile.connection_id = connection.id

    cfg = UserLLMConfig(
        provider=connection.provider,
        base_url=connection.base_url.rstrip("/"),
        api_key=decrypt(connection.api_key_enc),
        default_model=profile.model_id,
        complex_model=profile.model_id,
        context_window=profile.context_window,
        complex_enabled=False,
        model_context_windows={profile.model_id: profile.context_window},
        model_pricing_overrides={
            profile.model_id: override
            for override in [profile.pricing_override()]
            if override is not None
        },
        connection_id=connection.id,
    )
    return profile, cfg


async def ensure_legacy_llm_model_profiles(
    session: AsyncSession,
    user: "User",
) -> list[LLMModelProfile]:
    """Materialize existing default/complex choices as editable profiles.

    The migration is deliberately lazy and idempotent, so old deployments get
    a usable model list on their first settings/chat request without a data
    migration that needs to decrypt every user's secret.
    """
    cfg = resolve_user_llm(user)
    if cfg is None:
        return await list_llm_model_profiles(session, user_id=user.id)

    connection = await ensure_legacy_llm_connection(session, user)
    profiles = await list_llm_model_profiles(session, user_id=user.id)
    if connection is not None:
        for profile in profiles:
            if profile.connection_id is None:
                profile.connection_id = connection.id
    existing_models = {profile.model_id for profile in profiles}
    for model_id, label in (
        (cfg.default_model, "默认模型"),
        (cfg.complex_model, "复杂任务模型"),
        (cfg.triage_model or "", "快速意图模型"),
        (cfg.fallback_model or "", "备用模型"),
    ):
        if not model_id or model_id in existing_models:
            continue
        session.add(
            LLMModelProfile(
                id=str(uuid.uuid4()),
                user_id=user.id,
                connection_id=connection.id if connection else None,
                display_name=label if model_id == cfg.default_model else model_id,
                model_id=model_id,
                context_window=cfg.context_window,
            )
        )
        existing_models.add(model_id)
    await session.flush()
    profiles = await list_llm_model_profiles(session, user_id=user.id)
    # Lift old model-name policies into stable profile IDs.  Prefer the
    # default connection to make duplicate remote IDs deterministic.
    profile_for_model: dict[str, LLMModelProfile] = {}
    for profile in sorted(
        profiles,
        key=lambda item: (item.connection_id != (connection.id if connection else None), item.created_at),
    ):
        profile_for_model.setdefault(profile.model_id, profile)
    for field_name, model_id in (
        ("llm_default_profile_id", cfg.default_model),
        ("llm_complex_profile_id", cfg.complex_model),
        ("llm_triage_profile_id", cfg.triage_model),
        ("llm_fallback_profile_id", cfg.fallback_model),
    ):
        if not getattr(user, field_name, None):
            profile = profile_for_model.get(model_id or "")
            if profile is not None:
                setattr(user, field_name, profile.id)
    return profiles


async def resolve_user_llm_routing_configs(
    session: AsyncSession,
    user: "User",
) -> UserLLMRoutingConfigs | None:
    """Resolve profile-ID routing policy to independently authenticated cfgs."""
    legacy_cfg = resolve_user_llm(user)
    # New model profiles own their connection credentials.  They must remain
    # usable even when the user has never populated the legacy default fields.
    # Only materialise the compatibility profiles when such a legacy config
    # actually exists.
    if legacy_cfg is not None:
        await ensure_legacy_llm_model_profiles(session, user)

    async def _resolve(field_name: str) -> UserLLMConfig | None:
        selected = await resolve_llm_profile_config(
            session, user=user, profile_id=getattr(user, field_name, None)
        )
        return selected[1] if selected is not None else None

    primary = await _resolve("llm_default_profile_id") or legacy_cfg
    if primary is None:
        return None
    complex_cfg = await _resolve("llm_complex_profile_id")
    triage_cfg = await _resolve("llm_triage_profile_id")
    fallback_cfg = await _resolve("llm_fallback_profile_id")
    return UserLLMRoutingConfigs(
        primary=primary,
        complex=complex_cfg if bool(getattr(user, "llm_complex_enabled", False)) else None,
        triage=triage_cfg,
        fallback=fallback_cfg,
    )


def with_model_profile_context(
    cfg: UserLLMConfig | None,
    profiles: list[LLMModelProfile],
) -> UserLLMConfig | None:
    """Attach per-profile capacities to an otherwise legacy-compatible cfg."""
    if cfg is None:
        return None
    windows = {profile.model_id: profile.context_window for profile in profiles if profile.enabled}
    return replace(cfg, model_context_windows=windows)


def configured_context_window_for_model(cfg: UserLLMConfig | None, model: str | None) -> int | None:
    if cfg is None:
        return None
    # A few internal integrations intentionally pass a light config-shaped
    # object instead of the full dataclass. Treat missing profile windows as an
    # empty mapping so the legacy connection-wide window remains usable.
    model_windows = getattr(cfg, "model_context_windows", {}) or {}
    if model and model in model_windows:
        return model_windows[model]
    return getattr(cfg, "context_window", None)


def resolve_user_embedding(user: "User") -> Optional[UserEmbeddingConfig]:
    """Return user's embedding config, or None to fall back to env."""
    if not _embedding_is_configured(user):
        return None
    return UserEmbeddingConfig(
        provider=user.embedding_provider or "",
        base_url=(user.embedding_base_url or "").rstrip("/"),
        api_key=decrypt(user.embedding_api_key_enc or ""),
        model=user.embedding_model or "",
        dim=int(user.embedding_dim or 0),
    )


def resolve_user_reranker(user: "User") -> Optional[UserRerankerConfig]:
    """Return user's reranker config, or None when disabled / unconfigured.

    Unlike LLM and embedding, there is no env fallback — reranker is fully
    opt-in (default off). Callers that get None must skip reranking entirely.
    """
    if not _reranker_is_configured(user):
        return None
    enc = getattr(user, "reranker_api_key_enc", None) or ""
    return UserRerankerConfig(
        provider=user.reranker_provider or "",
        base_url=(user.reranker_base_url or "").rstrip("/"),
        api_key=decrypt(enc) if enc else "",
        model=user.reranker_model or "",
    )
