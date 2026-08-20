"""Versioned, deterministic retrieval and constrained-runtime evaluation."""

from .metrics import (
    EvaluationGateError,
    RAGGoldenCase,
    collapse_retrieved_to_documents,
    evaluate,
    load_cases,
    load_gate,
    load_predictions,
    parse_cases_jsonl,
    parse_gate,
    parse_gate_json,
    parse_predictions_jsonl,
    search_overfetch_limit,
    unique_ids,
)
from .react_runtime import (
    ReactEvaluationError,
    ReactGoldenCase,
    assert_react_quality_gate,
    evaluate_react_cases,
    load_react_cases,
    parse_react_cases_jsonl,
)

__all__ = [
    "EvaluationGateError",
    "RAGGoldenCase",
    "collapse_retrieved_to_documents",
    "evaluate",
    "load_cases",
    "load_gate",
    "load_predictions",
    "parse_cases_jsonl",
    "parse_gate",
    "parse_gate_json",
    "parse_predictions_jsonl",
    "search_overfetch_limit",
    "unique_ids",
    "ReactEvaluationError",
    "ReactGoldenCase",
    "assert_react_quality_gate",
    "evaluate_react_cases",
    "load_react_cases",
    "parse_react_cases_jsonl",
]
