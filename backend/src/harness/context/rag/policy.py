"""Retrieval budgets — KB admission and web-search caps."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.settings import Settings, get_settings

WebSearchMode = Literal["general", "kb", "disabled"]


@dataclass(frozen=True)
class KBRetrievalPolicy:
    candidate_limit: int
    final_limit: int
    min_dense_score: float
    kg_skip_if_dense_score_ge: float


@dataclass(frozen=True)
class WebSearchPolicy:
    max_calls: int
    results_per_call: int
    evidence_limit: int


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


def resolve_web_search_policy(
    mode: WebSearchMode, settings: Settings | None = None
) -> WebSearchPolicy:
    """Return bounded server-side web-search limits for one agent request."""
    if mode == "disabled":
        return WebSearchPolicy(max_calls=0, results_per_call=0, evidence_limit=0)
    current = settings or get_settings()
    if mode == "kb":
        max_calls = _bounded_int(current.kb_web_search_max_calls, default=1, minimum=1, maximum=3)
        results = _bounded_int(
            current.kb_web_search_results_per_call, default=3, minimum=1, maximum=5
        )
        evidence = _bounded_int(
            current.kb_web_search_evidence_limit, default=3, minimum=1, maximum=5
        )
    else:
        max_calls = _bounded_int(
            current.general_web_search_max_calls, default=2, minimum=1, maximum=3
        )
        results = _bounded_int(
            current.general_web_search_results_per_call, default=5, minimum=1, maximum=5
        )
        evidence = _bounded_int(
            current.general_web_search_evidence_limit, default=5, minimum=1, maximum=10
        )
    return WebSearchPolicy(
        max_calls=max_calls,
        results_per_call=results,
        evidence_limit=evidence,
    )
