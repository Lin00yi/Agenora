"""Classify KB recall: empty store vs below-threshold miss vs admitted hit."""
from __future__ import annotations

from typing import Any

from src.capabilities.knowledge.application.retrieval import (
    RetrievalAssessment,
    RetrievalStatus,
    admit_hits,
    normalized_score,
)

__all__ = [
    "RetrievalAssessment",
    "RetrievalStatus",
    "admit_hits",
    "assessment_from_tool_raw",
    "is_empty_injected_evidence",
    "merge_assessments",
    "normalized_score",
]


def merge_assessments(parts: list[RetrievalAssessment]) -> RetrievalAssessment:
    if not parts:
        return RetrievalAssessment(
            status="empty",
            candidate_count=0,
            admitted_count=0,
            max_score=0.0,
            min_dense_score=0.0,
        )
    candidate_count = sum(p.candidate_count for p in parts)
    admitted_count = sum(p.admitted_count for p in parts)
    max_score = max(p.max_score for p in parts)
    min_dense_score = parts[0].min_dense_score
    if candidate_count == 0:
        status: RetrievalStatus = "empty"
    elif admitted_count == 0:
        status = "miss"
    else:
        status = "hit"
    return RetrievalAssessment(
        status=status,
        candidate_count=candidate_count,
        admitted_count=admitted_count,
        max_score=max_score,
        min_dense_score=min_dense_score,
    )


def assessment_from_tool_raw(raw: Any) -> RetrievalAssessment | None:
    if not isinstance(raw, dict):
        return None
    if "candidate_hits" not in raw and "hits" not in raw:
        return None
    try:
        candidate_count = int(raw.get("candidate_hits") or 0)
        admitted_count = int(raw.get("hits") or 0)
        max_score = normalized_score(raw.get("max_score"))
        min_dense_score = normalized_score(raw.get("min_dense_score"))
    except (TypeError, ValueError):
        return None
    if candidate_count == 0:
        status: RetrievalStatus = "empty"
    elif admitted_count == 0:
        status = "miss"
    else:
        status = "hit"
    return RetrievalAssessment(
        status=status,
        candidate_count=candidate_count,
        admitted_count=admitted_count,
        max_score=max_score,
        min_dense_score=min_dense_score,
    )


def is_empty_injected_evidence(evidence: list[Any] | None) -> bool:
    """True when the reason node has no admitted KB/KG chunks to inject."""
    return not bool(evidence)
