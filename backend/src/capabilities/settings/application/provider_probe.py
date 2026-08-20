"""Provider-probe use cases behind the settings capability boundary."""

from src.adapters.llm.probe import (
    EmbeddingProbeResult,
    ProbeError,
    _probe_openai_compat_models,
    probe_embedding,
    probe_llm_models,
)


async def probe_openai_compat_models(base_url: str, api_key: str) -> list[str]:
    return await _probe_openai_compat_models(base_url, api_key)


__all__ = [
    "EmbeddingProbeResult",
    "ProbeError",
    "probe_embedding",
    "probe_llm_models",
    "probe_openai_compat_models",
]
