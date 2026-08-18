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


def test_duplicate_chunks_of_one_document_do_not_inflate_recall(tmp_path):
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text(
        json.dumps({"id": "a", "query": "A", "expected_document_ids": ["doc-a"]}) + "\n",
        encoding="utf-8",
    )
    report = evaluate(
        load_cases(dataset),
        {
            "a": {
                "id": "a",
                "retrieved": [
                    {"document_id": "doc-a"},
                    {"document_id": "doc-a"},
                    {"document_id": "doc-b"},
                ],
            }
        },
        k=3,
    )
    assert report["per_case"][0]["retrieved_document_ids"] == ["doc-a", "doc-b"]
    assert report["metrics"]["recall_at_k"] == pytest.approx(1.0)
    assert report["metrics"]["mrr"] == pytest.approx(1.0)
    assert report["metrics"]["precision_at_k"] == pytest.approx(0.5)


def test_allowed_document_set_counts_any_labeled_hit(tmp_path):
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "card",
                "query": "overview",
                "expected_document_ids": ["canonical", "related"],
                "expected_citation_document_ids": ["canonical"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = evaluate(
        load_cases(dataset),
        {"card": {"id": "card", "retrieved": [{"document_id": "related"}, {"document_id": "other"}]}},
        k=3,
    )
    assert report["metrics"]["recall_at_k"] == pytest.approx(0.5)
    assert report["metrics"]["mrr"] == pytest.approx(1.0)


def test_recall_at_k_is_normalized_by_cutoff_when_more_docs_are_relevant(tmp_path):
    dataset = tmp_path / "golden.jsonl"
    dataset.write_text(
        json.dumps({"id": "a", "query": "A", "expected_document_ids": ["a", "b", "c", "d"]}) + "\n",
        encoding="utf-8",
    )
    report = evaluate(
        load_cases(dataset),
        {"a": {"id": "a", "retrieved": [{"document_id": "a"}, {"document_id": "b"}, {"document_id": "x"}]}},
        k=3,
    )
    assert report["metrics"]["recall_at_k"] == pytest.approx(2 / 3)


def test_load_gate_reads_minimums(tmp_path):
    from src.rag_eval.metrics import load_gate

    gate = tmp_path / "gate.json"
    gate.write_text(
        json.dumps(
            {
                "dataset": "config/rag_eval_roogoo.jsonl",
                "kb_id": "kb-1",
                "k": 3,
                "minimums": {"recall_at_k": 0.8, "mrr": 0.7, "ndcg_at_k": 0.75},
            }
        ),
        encoding="utf-8",
    )
    loaded = load_gate(gate)
    assert loaded["dataset"] == "config/rag_eval_roogoo.jsonl"
    assert loaded["kb_id"] == "kb-1"
    assert loaded["minimums"]["recall_at_k"] == 0.8
