"""Regression coverage for bounded checkpoint maintenance."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "maintain_checkpoints.py"
SPEC = importlib.util.spec_from_file_location("maintain_checkpoints", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
maintenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maintenance)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        );
        CREATE TABLE writes (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        );
        """
    )
    return connection


def test_scan_candidates_uses_checkpoint_namespace_retention() -> None:
    connection = _connection()
    connection.executemany(
        "INSERT INTO checkpoints VALUES (?, ?, ?)",
        [
            ("thread-a", "", "003"),
            ("thread-a", "", "002"),
            ("thread-a", "", "001"),
            ("thread-a", "child", "002"),
            ("thread-a", "child", "001"),
        ],
    )
    batches: list[list[tuple[str, str, str]]] = []

    total, candidates = maintenance._scan_candidates(
        connection,
        keep_per_thread=1,
        on_batch=batches.append,
    )

    assert total == 5
    assert candidates == 3
    assert batches == [[("thread-a", "", "002"), ("thread-a", "", "001"), ("thread-a", "child", "001")]]


def test_scan_and_delete_remains_correct_across_small_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _connection()
    rows = [("thread-a", "", f"{number:03d}") for number in range(12, 0, -1)]
    connection.executemany("INSERT INTO checkpoints VALUES (?, ?, ?)", rows)
    connection.executemany(
        "INSERT INTO writes VALUES (?, ?, ?, ?, ?)",
        [(thread_id, namespace, checkpoint_id, "task", 0) for thread_id, namespace, checkpoint_id in rows],
    )
    monkeypatch.setattr(maintenance, "_SCAN_BATCH_SIZE", 3)
    deleted = [0, 0]

    def delete_batch(batch: list[tuple[str, str, str]]) -> None:
        checkpoints, writes = maintenance._delete(connection, batch)
        deleted[0] += checkpoints
        deleted[1] += writes

    total, candidates = maintenance._scan_candidates(
        connection,
        keep_per_thread=2,
        on_batch=delete_batch,
    )

    assert total == 12
    assert candidates == 10
    assert deleted == [10, 10]
    assert connection.execute("SELECT checkpoint_id FROM checkpoints ORDER BY checkpoint_id DESC").fetchall() == [
        ("012",),
        ("011",),
    ]


def test_require_vacuum_space_rejects_insufficient_target_volume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(maintenance, "disk_usage", lambda _: type("Usage", (), {"free": 100})())

    with pytest.raises(ValueError, match="insufficient free space"):
        maintenance._require_vacuum_space(target=tmp_path / "compacted.db", source_bytes=100)
