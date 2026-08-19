"""Model-profile routing contracts that do not require a provider call."""
from __future__ import annotations

from src.models.gateway import (
    pick_model,
    resolve_empty_answer_fallback_model,
    should_route_to_complex,
)
from src.settings_user.models import UserLLMConfig, configured_context_window_for_model


def _config(**overrides) -> UserLLMConfig:
    values = {
        "provider": "openai-compat",
        "base_url": "https://example.invalid/v1",
        "api_key": "test",
        "default_model": "primary",
        "complex_model": "complex",
        "context_window": None,
        "complex_enabled": True,
        "triage_model": "flash",
        "fallback_model": "backup",
        "model_context_windows": {"primary": 128_000, "complex": 64_000, "flash": 16_000},
    }
    values.update(overrides)
    return UserLLMConfig(**values)


def test_profile_context_window_is_scoped_to_the_selected_model() -> None:
    cfg = _config(context_window=200_000)

    assert configured_context_window_for_model(cfg, "primary") == 128_000
    assert configured_context_window_for_model(cfg, "complex") == 64_000
    assert configured_context_window_for_model(cfg, "unknown") == 200_000


def test_complex_route_can_be_disabled_without_losing_the_profile() -> None:
    cfg = _config(complex_enabled=False)

    assert pick_model([{"role": "user", "content": "x" * 2_001}], [{"name": "tool"}] * 6, cfg) == "primary"


def test_complex_threshold_can_select_a_separate_profile_connection() -> None:
    cfg = _config(complex_enabled=True)

    assert should_route_to_complex(
        [{"role": "user", "content": "x" * 2_001}], [], cfg
    )


def test_empty_answer_prefers_an_explicit_backup_model() -> None:
    cfg = _config()

    assert resolve_empty_answer_fallback_model("primary", cfg) == "backup"
