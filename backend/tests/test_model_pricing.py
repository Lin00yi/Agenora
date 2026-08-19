from types import SimpleNamespace

from src.models.gateway import CostTracker
from src.models.catalog import resolve_model_pricing
from src.settings_user.models import UserLLMConfig


def _cfg(**overrides) -> UserLLMConfig:
    values = {
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key": "test",
        "default_model": "claude-haiku-4-5-20251001",
        "complex_model": "claude-haiku-4-5-20251001",
        "context_window": None,
    }
    values.update(overrides)
    return UserLLMConfig(**values)


def test_models_dev_pricing_is_available_for_anthropic_bare_model_id() -> None:
    pricing = resolve_model_pricing("claude-haiku-4-5-20251001", provider="anthropic")

    assert pricing is not None
    assert pricing.input == 1
    assert pricing.output == 5


def test_cost_tracker_uses_models_dev_cache_prices_when_present() -> None:
    tracker = CostTracker()
    tracker.add(
        "claude-haiku-4-5-20251001",
        SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000),
        cfg=_cfg(),
    )

    assert tracker.total_usd == 6
    assert tracker.has_unknown_price is False


def test_profile_override_wins_over_catalog_price() -> None:
    tracker = CostTracker()
    cfg = _cfg(
        provider="openai-compat",
        default_model="reseller-model",
        complex_model="reseller-model",
        model_pricing_overrides={
            "reseller-model": {"input": 2.5, "output": 7.5, "cache_read": None, "cache_write": None}
        },
    )
    tracker.add(
        "reseller-model",
        SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=1_000_000),
        cfg=cfg,
    )

    assert tracker.total_usd == 10


def test_unknown_model_does_not_receive_a_fictitious_price() -> None:
    tracker = CostTracker()
    tracker.add(
        "private-gateway-model",
        SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        cfg=_cfg(provider="openai-compat"),
    )

    assert tracker.total_usd is None
    assert tracker.has_unknown_price is True
    assert tracker.calls[-1]["usd"] is None
