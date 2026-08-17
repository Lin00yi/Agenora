"""Single source of truth for KB retrieval tuning.

These values affect query planning, vector/BM25 candidate collection, evidence
admission, and the optional KG fallback.  Keeping them together prevents a
prompt default from drifting away from the tool's enforced limit.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.settings import Settings, get_settings


@dataclass(frozen=True)
class KBRetrievalPolicy:
    candidate_limit: int
    final_limit: int
    min_dense_score: float
    kg_skip_if_dense_score_ge: float


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return max(minimum, min(default, maximum))


def _bounded_score(value: object, *, default: float) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def resolve_kb_retrieval_policy(settings: Settings | None = None) -> KBRetrievalPolicy:
    """Resolve bounded KB retrieval settings for all runtime call paths."""
    current = settings or get_settings()
    final_limit = _bounded_int(
        current.kb_retrieval_final_limit, default=3, minimum=1, maximum=10
    )
    return KBRetrievalPolicy(
        candidate_limit=max(
            final_limit,
            _bounded_int(current.kb_retrieval_candidate_limit, default=6, minimum=1, maximum=30),
        ),
        final_limit=final_limit,
        min_dense_score=_bounded_score(current.kb_retrieval_min_dense_score, default=0.4),
        kg_skip_if_dense_score_ge=_bounded_score(
            current.kb_kg_skip_if_dense_score_ge, default=0.7
        ),
    )
