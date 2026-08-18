"""Versioned, deterministic RAG retrieval and citation evaluation."""

from .metrics import (
    EvaluationGateError,
    RAGGoldenCase,
    collapse_retrieved_to_documents,
    evaluate,
    load_cases,
    load_gate,
    load_predictions,
    search_overfetch_limit,
    unique_ids,
)

__all__ = [
    "EvaluationGateError",
    "RAGGoldenCase",
    "collapse_retrieved_to_documents",
    "evaluate",
    "load_cases",
    "load_gate",
    "load_predictions",
    "search_overfetch_limit",
    "unique_ids",
]
