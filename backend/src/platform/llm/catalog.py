"""Offline model capability catalog generated from the models.dev SDK snapshot.

The request path intentionally reads a checked-in snapshot rather than calling
models.dev. This keeps context budgeting deterministic and available when a
user's model provider (or the public internet) is unavailable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


# ``catalog.py`` lives at ``src/platform/llm``; the checked-in runtime data
# remains owned by the backend deployment root rather than any package layer.
_CATALOG_PATH = Path(__file__).resolve().parents[3] / "config" / "models.dev.snapshot.json"


@dataclass(frozen=True)
class ModelCatalogEntry:
    canonical_id: str
    model_id: str
    name: str
    lab: str
    context_window: int
    max_output_tokens: int | None
    pricing: "ModelPricing | None"
    logo_url: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "name": self.name,
            "lab": self.lab,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "pricing": self.pricing.to_public_dict() if self.pricing else None,
            "logo_url": self.logo_url,
        }


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1M tokens from the models.dev offline catalog."""

    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None

    def to_public_dict(self) -> dict[str, float | None]:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }


def _normalize_model_id(model: str) -> str:
    return model.strip().lower()


def _parse_pricing(raw: Any) -> ModelPricing | None:
    if not isinstance(raw, dict):
        return None
    try:
        input_price = float(raw["input"])
        output_price = float(raw["output"])
    except (KeyError, TypeError, ValueError):
        return None
    if input_price < 0 or output_price < 0:
        return None

    def _optional_price(name: str) -> float | None:
        value = raw.get(name)
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    return ModelPricing(
        input=input_price,
        output=output_price,
        cache_read=_optional_price("cache_read"),
        cache_write=_optional_price("cache_write"),
    )


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, ModelCatalogEntry], dict[str, tuple[str, ...]]]:
    """Load generated data once, accepting a missing/corrupt catalog safely."""
    try:
        payload: dict[str, Any] = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}

    entries: dict[str, ModelCatalogEntry] = {}
    for item in payload.get("models", []):
        try:
            entry = ModelCatalogEntry(
                canonical_id=str(item["canonical_id"]),
                model_id=str(item["model_id"]),
                name=str(item["name"]),
                lab=str(item["lab"]),
                context_window=int(item["context_window"]),
                max_output_tokens=int(item["max_output_tokens"]) if item.get("max_output_tokens") is not None else None,
                pricing=_parse_pricing(item.get("pricing")),
                logo_url=str(item["logo_url"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if entry.context_window >= 4_096:
            entries[_normalize_model_id(entry.canonical_id)] = entry

    by_model_id: dict[str, tuple[str, ...]] = {}
    for model_id, canonical_ids in payload.get("model_ids", {}).items():
        if not isinstance(canonical_ids, list):
            continue
        resolved = tuple(
            _normalize_model_id(canonical_id)
            for canonical_id in canonical_ids
            if _normalize_model_id(canonical_id) in entries
        )
        if resolved:
            by_model_id[_normalize_model_id(str(model_id))] = resolved
    return entries, by_model_id


def resolve_model_catalog_entry(model: str | None) -> ModelCatalogEntry | None:
    """Find an exact canonical or unambiguous bare model identifier.

    Some distributors expose the same bare ID with different capacities. In
    that case callers keep the conservative fallback (or request a user
    override), rather than guessing a potentially unsafe capacity.
    """
    if not model or not model.strip():
        return None
    entries, by_model_id = _catalog()
    normalized = _normalize_model_id(model)
    if direct := entries.get(normalized):
        return direct
    candidates = by_model_id.get(normalized, ())
    if len(candidates) == 1:
        return entries[candidates[0]]
    return None


def resolve_model_pricing(model: str | None, *, provider: str | None = None) -> ModelPricing | None:
    """Resolve pricing without guessing across ambiguous reseller model IDs.

    Anthropic's Messages API has an unambiguous vendor namespace. For generic
    OpenAI-compatible connections, a bare model ID is only accepted when the
    offline catalog maps it to one lab; callers can supply a profile override
    for proxies or resellers whose price differs from the vendor list.
    """
    if not model or not model.strip():
        return None
    entries, by_model_id = _catalog()
    normalized = _normalize_model_id(model)
    if entry := entries.get(normalized):
        return entry.pricing
    if provider == "anthropic":
        entry = entries.get(f"anthropic/{normalized}")
        return entry.pricing if entry else None
    candidates = by_model_id.get(normalized, ())
    if len(candidates) == 1:
        return entries[candidates[0]].pricing
    return None
