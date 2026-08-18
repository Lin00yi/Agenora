"""Portable metrics for the Agenora RAG golden-set contract.

This module intentionally evaluates stable identifiers, not an LLM-as-judge:
the resulting Recall@K / MRR / nDCG and citation precision are deterministic
enough to gate a retrieval or reranker rollout in CI.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class EvaluationGateError(ValueError):
    """Raised for invalid versioned evaluation fixtures or a failed quality gate."""


@dataclass(frozen=True)
class RAGGoldenCase:
    id: str
    query: str
    expected_document_ids: frozenset[str]
    expected_citation_document_ids: frozenset[str]
    tags: tuple[str, ...] = ()


def _string_set(value: object, *, field: str, case_id: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise EvaluationGateError(f"case {case_id}: {field} must be a non-empty string list")
    values = frozenset(str(item).strip() for item in value if str(item).strip())
    if not values:
        raise EvaluationGateError(f"case {case_id}: {field} must contain at least one id")
    return values


def load_cases(path: str | Path) -> list[RAGGoldenCase]:
    """Load a checked-in JSONL golden set and reject ambiguous fixtures."""
    source = Path(path)
    cases: list[RAGGoldenCase] = []
    seen: set[str] = set()
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationGateError(f"{source}:{number}: invalid JSON") from exc
        if not isinstance(raw, dict):
            raise EvaluationGateError(f"{source}:{number}: case must be an object")
        case_id = str(raw.get("id") or "").strip()
        query = str(raw.get("query") or "").strip()
        if not case_id or not query:
            raise EvaluationGateError(f"{source}:{number}: id and query are required")
        if case_id in seen:
            raise EvaluationGateError(f"{source}:{number}: duplicate case id {case_id}")
        seen.add(case_id)
        expected = _string_set(raw.get("expected_document_ids"), field="expected_document_ids", case_id=case_id)
        citations_raw = raw.get("expected_citation_document_ids", list(expected))
        citations = _string_set(
            citations_raw, field="expected_citation_document_ids", case_id=case_id
        )
        tags = raw.get("tags") or []
        if not isinstance(tags, list):
            raise EvaluationGateError(f"case {case_id}: tags must be a string list")
        cases.append(
            RAGGoldenCase(
                id=case_id,
                query=query,
                expected_document_ids=expected,
                expected_citation_document_ids=citations,
                tags=tuple(str(tag).strip() for tag in tags if str(tag).strip()),
            )
        )
    if not cases:
        raise EvaluationGateError(f"{source}: no evaluation cases")
    return cases


def load_predictions(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load evaluator output JSONL keyed by golden case id."""
    source = Path(path)
    rows: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationGateError(f"{source}:{number}: invalid JSON") from exc
        if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
            raise EvaluationGateError(f"{source}:{number}: prediction must contain id")
        case_id = str(raw["id"]).strip()
        if case_id in rows:
            raise EvaluationGateError(f"{source}:{number}: duplicate prediction id {case_id}")
        rows[case_id] = raw
    return rows


def _document_ids(row: dict[str, Any], field: str) -> list[str]:
    entries = row.get(field) or []
    if not isinstance(entries, list):
        return []
    out: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            value = entry.strip()
        elif isinstance(entry, dict):
            value = str(entry.get("document_id") or entry.get("doc_id") or "").strip()
        else:
            value = ""
        if value:
            out.append(value)
    return out


def _dcg(relevant_at_rank: Iterable[bool]) -> float:
    return sum(1.0 / math.log2(rank + 1) for rank, relevant in enumerate(relevant_at_rank, start=1) if relevant)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def evaluate(
    cases: list[RAGGoldenCase],
    predictions: dict[str, dict[str, Any]],
    *,
    k: int = 3,
) -> dict[str, Any]:
    """Evaluate ranked retrieval and answer citations against the golden set."""
    top_k = max(1, min(int(k), 100))
    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    citation_precisions: list[float] = []
    citation_recalls: list[float] = []
    missing: list[str] = []
    per_case: list[dict[str, Any]] = []

    for case in cases:
        row = predictions.get(case.id)
        if row is None:
            missing.append(case.id)
            retrieved: list[str] = []
            citations: list[str] = []
            has_citation_judgment = False
        else:
            retrieved = _document_ids(row, "retrieved")[:top_k]
            citations = _document_ids(row, "citations")
            # A retrieval-only run deliberately has no answer citations. Do
            # not turn that absence into a misleading zero-quality score.
            has_citation_judgment = "citations" in row
        relevant = [doc_id in case.expected_document_ids for doc_id in retrieved]
        hits = sum(relevant)
        recalls.append(hits / len(case.expected_document_ids))
        precisions.append(hits / len(retrieved) if retrieved else 0.0)
        first_hit = next((rank for rank, ok in enumerate(relevant, start=1) if ok), None)
        reciprocal_ranks.append(1.0 / first_hit if first_hit is not None else 0.0)
        ideal = _dcg([True] * min(len(case.expected_document_ids), top_k))
        ndcgs.append(_dcg(relevant) / ideal if ideal else 0.0)

        citation_hits = sum(doc_id in case.expected_citation_document_ids for doc_id in citations)
        if has_citation_judgment:
            if citations:
                citation_precisions.append(citation_hits / len(citations))
            # Citation recall is meaningful when an answer was supplied even
            # when that answer omitted all citations.
            citation_recalls.append(citation_hits / len(case.expected_citation_document_ids))
        per_case.append(
            {
                "id": case.id,
                "tags": list(case.tags),
                "retrieved_document_ids": retrieved,
                "expected_document_ids": sorted(case.expected_document_ids),
                "citation_document_ids": citations,
                "expected_citation_document_ids": sorted(case.expected_citation_document_ids),
                "recall": recalls[-1],
                "mrr": reciprocal_ranks[-1],
                "ndcg": ndcgs[-1],
                "citation_recall": citation_recalls[-1] if has_citation_judgment else None,
                "citation_precision": citation_precisions[-1] if citations else None,
            }
        )

    return {
        "schema_version": 1,
        "case_count": len(cases),
        "prediction_count": len(predictions),
        "missing_prediction_ids": missing,
        "k": top_k,
        "metrics": {
            "recall_at_k": _mean(recalls),
            "precision_at_k": _mean(precisions),
            "mrr": _mean(reciprocal_ranks),
            "ndcg_at_k": _mean(ndcgs),
            "citation_precision": _mean(citation_precisions),
            "citation_recall": _mean(citation_recalls),
        },
        "per_case": per_case,
    }


def assert_quality_gate(
    report: dict[str, Any],
    *,
    min_recall_at_k: float | None = None,
    min_mrr: float | None = None,
    min_ndcg_at_k: float | None = None,
    min_citation_precision: float | None = None,
    max_missing_cases: int = 0,
) -> None:
    """Fail predictably when an evaluation report is below an explicit baseline."""
    failures: list[str] = []
    missing = len(report.get("missing_prediction_ids") or [])
    if missing > max(0, int(max_missing_cases)):
        failures.append(f"missing cases {missing} > {max_missing_cases}")
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    checks = (
        ("recall_at_k", min_recall_at_k),
        ("mrr", min_mrr),
        ("ndcg_at_k", min_ndcg_at_k),
        ("citation_precision", min_citation_precision),
    )
    for name, threshold in checks:
        if threshold is None:
            continue
        value = metrics.get(name)
        if value is None or float(value) < float(threshold):
            failures.append(f"{name} {value!r} < {float(threshold):.3f}")
    if failures:
        raise EvaluationGateError("RAG quality gate failed: " + "; ".join(failures))


def report_json(report: dict[str, Any]) -> str:
    """Stable pretty JSON for CI artifacts and reviewable baseline diffs."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
