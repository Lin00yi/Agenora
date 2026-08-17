"""Central policy for web-search call and evidence budgets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.settings import Settings, get_settings

WebSearchMode = Literal["general", "kb", "disabled"]


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
