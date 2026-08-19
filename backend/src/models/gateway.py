"""LLM client wrapper supporting Anthropic and OpenAI-compatible providers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.settings import get_settings

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig

# DeepSeek retired this identifier. Keep this normalization at the request
# boundary too: deployment environments can still have an old explicit env
# value even after their database rows are migrated on startup.
LEGACY_MODEL_ALIASES = {
    "deepseek-chat": "deepseek-v4-flash",
}


def normalize_model_name(model: str | None) -> str | None:
    """Return a vendor-supported model identifier for known retired aliases."""
    if model is None:
        return None
    return LEGACY_MODEL_ALIASES.get(model.strip(), model.strip())


@dataclass
class CostTracker:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    usd: float = 0.0
    has_unknown_price: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_usd(self) -> float | None:
        """Return a total only when every tracked provider call was priced."""
        return None if self.has_unknown_price else self.usd

    def add(self, model: str, usage: Any, *, cfg: "UserLLMConfig | None" = None) -> None:
        """Add provider-reported usage using a profile override or models.dev.

        Never use a made-up fallback price: a partial total is worse than an
        explicit unknown total when a custom gateway bills differently.
        """
        from src.models.catalog import ModelPricing, resolve_model_pricing

        override = (getattr(cfg, "model_pricing_overrides", {}) or {}).get(model)
        if override is not None:
            try:
                price = ModelPricing(
                    input=float(override["input"]),
                    output=float(override["output"]),
                    cache_read=(
                        float(override["cache_read"])
                        if override.get("cache_read") is not None
                        else None
                    ),
                    cache_write=(
                        float(override["cache_write"])
                        if override.get("cache_write") is not None
                        else None
                    ),
                )
            except (KeyError, TypeError, ValueError):
                price = None
        else:
            price = resolve_model_pricing(model, provider=getattr(cfg, "provider", None))
        in_t = getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0)
        out_t = getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0)
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0

        self.input_tokens += in_t
        self.output_tokens += out_t
        self.cache_read_tokens += cache_read
        self.cache_creation_tokens += cache_create

        if price is None:
            self.has_unknown_price = True
            self.calls.append(
                {"model": model, "in": in_t, "out": out_t, "cache_read": cache_read, "usd": None}
            )
            return

        # Some catalog entries do not publish cache prices. Anthropic's
        # standard 10% read / 125% write rule is retained only as a documented
        # fallback for those entries, never as a fallback for model pricing.
        cache_read_price = price.cache_read if price.cache_read is not None else price.input * 0.1
        cache_write_price = price.cache_write if price.cache_write is not None else price.input * 1.25
        call_cost = (
            in_t * price.input / 1_000_000
            + out_t * price.output / 1_000_000
            + cache_read * cache_read_price / 1_000_000
            + cache_create * cache_write_price / 1_000_000
        )
        self.usd += call_cost
        self.calls.append(
            {"model": model, "in": in_t, "out": out_t, "cache_read": cache_read, "usd": call_cost}
        )


def get_client(cfg: "UserLLMConfig | None" = None):
    """Return appropriate client. If cfg is given, use user creds; else fall back to env."""
    if cfg is not None:
        if cfg.provider == "anthropic":
            from anthropic import AsyncAnthropic
            return AsyncAnthropic(api_key=cfg.api_key, base_url=cfg.base_url)
        # openai-compat covers DeepSeek, OpenAI, vLLM, Together, Groq, LMStudio, etc.
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

    s = get_settings()
    if s.llm_provider == "deepseek":
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=s.deepseek_api_key, base_url=s.deepseek_base_url)
    from anthropic import AsyncAnthropic
    return AsyncAnthropic(api_key=s.anthropic_api_key, base_url=s.anthropic_base_url)


def should_route_to_complex(
    messages: list[dict], tools: list[dict], cfg: "UserLLMConfig | None" = None
) -> bool:
    """Deterministic complexity threshold shared by model and config routing."""
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    text_len = 0
    if last_user:
        content = last_user.get("content", "")
        if isinstance(content, str):
            text_len = len(content)
        elif isinstance(content, list):
            text_len = sum(len(b.get("text", "")) for b in content if isinstance(b, dict))
    # Upgrade to complex model if many tools OR very long user input.
    return bool(getattr(cfg, "complex_enabled", True) and (len(tools) > 5 or text_len > 2000))


def pick_model(messages: list[dict], tools: list[dict], cfg: "UserLLMConfig | None" = None) -> str:
    """Route between default and complex model."""
    if cfg is not None:
        default_model = cfg.default_model
        complex_model = cfg.complex_model or cfg.default_model
    else:
        s = get_settings()
        default_model = s.llm_default_model
        complex_model = s.llm_complex_model

    default_model = normalize_model_name(default_model) or default_model
    complex_model = normalize_model_name(complex_model) or complex_model
    return complex_model if should_route_to_complex(messages, tools, cfg) else default_model


def resolve_empty_answer_fallback_model(
    current_model: str,
    cfg: "UserLLMConfig | None" = None,
) -> str | None:
    """Pick a different model for empty-answer escalation (usually complex).

    Returns None when no distinct alternate is configured — callers should skip
    the second recovery attempt and use the user-facing fallback copy.
    """
    current = normalize_model_name(current_model) or (current_model or "").strip()
    if cfg is not None:
        default_model = cfg.default_model
        complex_model = cfg.complex_model or cfg.default_model
    else:
        s = get_settings()
        default_model = s.llm_default_model
        complex_model = s.llm_complex_model

    default_model = normalize_model_name(default_model) or default_model
    complex_model = normalize_model_name(complex_model) or complex_model

    fallback_model = getattr(cfg, "fallback_model", None) if cfg is not None else None
    fallback_model = normalize_model_name(fallback_model) or (fallback_model or "").strip()
    if fallback_model and fallback_model != current:
        return fallback_model
    # Empty-answer recovery is a resilience path, not normal automatic
    # complexity routing. A separately configured complex model remains a
    # valid one-shot fallback even when automatic upgrades are disabled.
    if complex_model and complex_model != current:
        return complex_model
    if default_model and default_model != current:
        return default_model
    return None


def with_cache_control(blocks: list[dict], cfg: "UserLLMConfig | None" = None) -> list[dict]:
    """Add cache_control to the last block for prompt caching (Anthropic only)."""
    provider = cfg.provider if cfg is not None else get_settings().llm_provider
    if provider != "anthropic" or not blocks:
        return blocks
    out = [dict(b) for b in blocks]
    out[-1]["cache_control"] = {"type": "ephemeral"}
    return out


_CONVERSATION_CONTEXT_MARKER = "\n\n# 会话上下文（仅供参考的数据）\n"


def system_blocks_with_prefix_cache_control(
    system_prompt: str, cfg: "UserLLMConfig | None" = None
) -> list[dict]:
    """Create Anthropic system blocks with a cache point before mutable context.

    Server-generated memories and summaries can change, but stable policy and
    tool guidance usually do not. A single cached system block made any change
    at its tail (historically every RAG result too) recreate the whole cache.
    Keep the cache checkpoint immediately after the stable prefix whenever the
    prompt composer has appended the conversation-context marker.
    """
    marker_index = system_prompt.find(_CONVERSATION_CONTEXT_MARKER)
    if marker_index <= 0:
        return with_cache_control([{"type": "text", "text": system_prompt}], cfg)

    stable_prefix = system_prompt[:marker_index]
    mutable_suffix = system_prompt[marker_index:]
    blocks = with_cache_control([{"type": "text", "text": stable_prefix}], cfg)
    blocks.append({"type": "text", "text": mutable_suffix})
    return blocks
