"""Per-user LLM / embedding self-config (v2-M1).

Reads encrypted API keys from User row, exposes resolved configs to call sites.
v2-M2 adds BYOK enforcement helpers (gate.py).
"""
from __future__ import annotations

from .gate import require_user_embedding, require_user_llm
from .models import (
    UserEmbeddingConfig,
    UserLLMConfig,
    UserLLMRoutingConfigs,
    UserRerankerConfig,
    configured_context_window_for_model,
    ensure_legacy_llm_connection,
    ensure_legacy_llm_model_profiles,
    list_llm_connections,
    list_llm_model_profiles,
    resolve_llm_profile_config,
    resolve_user_llm_routing_configs,
    resolve_system_llm,
    resolve_user_embedding,
    resolve_user_llm,
    resolve_user_reranker,
    with_model_profile_context,
)

__all__ = [
    "UserEmbeddingConfig",
    "UserLLMConfig",
    "UserLLMRoutingConfigs",
    "UserRerankerConfig",
    "configured_context_window_for_model",
    "ensure_legacy_llm_connection",
    "ensure_legacy_llm_model_profiles",
    "list_llm_model_profiles",
    "list_llm_connections",
    "resolve_llm_profile_config",
    "resolve_user_llm_routing_configs",
    "resolve_system_llm",
    "resolve_user_embedding",
    "resolve_user_llm",
    "resolve_user_reranker",
    "with_model_profile_context",
    "require_user_embedding",
    "require_user_llm",
]
