"""Versioned, deterministic RAG retrieval and citation evaluation."""

from .metrics import (
    EvaluationGateError,
    RAGGoldenCase,
    evaluate,
    load_cases,
    load_predictions,
)

__all__ = [
    "EvaluationGateError",
    "RAGGoldenCase",
    "evaluate",
    "load_cases",
    "load_predictions",
]
