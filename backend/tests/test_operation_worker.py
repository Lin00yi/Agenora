"""Regression coverage for local durable-operation worker topology."""
from __future__ import annotations

from types import SimpleNamespace

from src.bootstrap.workers import operations


def test_embedded_milvus_worker_processes_one_job_at_a_time(monkeypatch) -> None:
    monkeypatch.setattr(
        operations,
        "get_settings",
        lambda: SimpleNamespace(vector_store="milvus", milvus_uri="./data/milvus_local.db"),
    )

    assert operations.worker_batch_limit() == 1


def test_network_vector_store_worker_keeps_bounded_batch_throughput(monkeypatch) -> None:
    monkeypatch.setattr(
        operations,
        "get_settings",
        lambda: SimpleNamespace(vector_store="qdrant", milvus_uri=""),
    )

    assert operations.worker_batch_limit() == 100
