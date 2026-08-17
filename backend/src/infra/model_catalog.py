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


_CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.dev.snapshot.json"


@dataclass(frozen=True)
class ModelCatalogEntry:
    canonical_id: str
    model_id: str
    name: str
    lab: str
    context_window: int
    max_output_tokens: int | None
    logo_url: str

    def to_public_dict(self) -> dict[str, str | int | None]:
        return {
            "canonical_id": self.canonical_id,
            "name": self.name,
            "lab": self.lab,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "logo_url": self.logo_url,
        }


def _normalize_model_id(model: str) -> str:
    return model.strip().lower()


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
