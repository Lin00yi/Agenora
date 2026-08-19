"""Classify KB recall: empty store vs below-threshold miss vs admitted hit."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

RetrievalStatus = Literal["empty", "miss", "hit"]


@dataclass(frozen=True)
class RetrievalAssessment:
    status: RetrievalStatus
    candidate_count: int
    admitted_count: int
    max_score: float
    min_dense_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_count": self.candidate_count,
            "admitted_count": self.admitted_count,
            "max_score": self.max_score,
            "min_dense_score": self.min_dense_score,
        }


def normalized_score(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


def admit_hits(
    hits: list[dict[str, Any]],
    *,
    min_dense_score: float,
    final_limit: int,
    is_enabled: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], RetrievalAssessment]:
    """Filter enabled candidates, then admit those at/above the dense threshold."""
    enabled = [hit for hit in hits if is_enabled(hit)] if is_enabled else list(hits)
    candidate_count = len(enabled)
    max_score = max((normalized_score(hit.get("score")) for hit in enabled), default=0.0)
    admitted = [
        hit for hit in enabled if normalized_score(hit.get("score")) >= min_dense_score
    ][: max(0, int(final_limit))]
    if candidate_count == 0:
        status: RetrievalStatus = "empty"
    elif not admitted:
        status = "miss"
    else:
        status = "hit"
    return admitted, RetrievalAssessment(
        status=status,
        candidate_count=candidate_count,
        admitted_count=len(admitted),
        max_score=max_score,
        min_dense_score=float(min_dense_score),
    )


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
