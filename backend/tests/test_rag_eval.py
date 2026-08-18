from __future__ import annotations

import json

import pytest

from src.rag_eval.metrics import EvaluationGateError, assert_quality_gate, evaluate, load_cases


def test_golden_retrieval_and_citation_metrics_are_deterministic(tmp_path):
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps({"id": "a", "query": "A", "expected_document_ids": ["doc-a"], "tags": ["faq"]}),
                json.dumps({"id": "b", "query": "B", "expected_document_ids": ["doc-b", "doc-c"], "expected_citation_document_ids": ["doc-b"]}),
            ]
        ),
        encoding="utf-8",
    )
    report = evaluate(
        load_cases(dataset),
        {
            "a": {"id": "a", "retrieved": [{"document_id": "doc-a"}], "citations": [{"document_id": "doc-a"}]},
            "b": {"id": "b", "retrieved": [{"document_id": "doc-x"}, {"document_id": "doc-b"}], "citations": [{"document_id": "doc-x"}, {"document_id": "doc-b"}]},
        },
        k=2,
    )

    assert report["missing_prediction_ids"] == []
    assert report["metrics"]["recall_at_k"] == pytest.approx(0.75)
    assert report["metrics"]["mrr"] == pytest.approx(0.75)
    assert report["metrics"]["ndcg_at_k"] == pytest.approx(
        (1 + ((1 / 1.584962500721156) / 1.6309297535714573)) / 2
    )
    assert report["metrics"]["citation_precision"] == pytest.approx(0.75)
    assert report["metrics"]["citation_recall"] == pytest.approx(1.0)


def test_quality_gate_rejects_missing_or_regressed_cases(tmp_path):
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text(json.dumps({"id": "a", "query": "A", "expected_document_ids": ["doc-a"]}) + "\n", encoding="utf-8")
    report = evaluate(load_cases(dataset), {}, k=3)
    with pytest.raises(EvaluationGateError, match="missing cases"):
        assert_quality_gate(report, min_recall_at_k=0.8)


def test_retrieval_only_runs_leave_citation_metrics_unmeasured(tmp_path):
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text(
        json.dumps({"id": "a", "query": "A", "expected_document_ids": ["doc-a"]}) + "\n",
        encoding="utf-8",
    )
    report = evaluate(
        load_cases(dataset),
        {"a": {"id": "a", "retrieved": [{"document_id": "doc-a"}]}},
    )
    assert report["metrics"]["citation_precision"] is None
    assert report["metrics"]["citation_recall"] is None
    assert report["per_case"][0]["citation_recall"] is None


def test_golden_case_requires_real_expected_document_ids(tmp_path):
    dataset = tmp_path / "invalid.jsonl"
    dataset.write_text('{"id":"x","query":"q","expected_document_ids":[]}\n', encoding="utf-8")
    with pytest.raises(EvaluationGateError, match="non-empty"):
        load_cases(dataset)
