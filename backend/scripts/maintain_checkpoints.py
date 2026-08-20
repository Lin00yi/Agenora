"""Inspect or compact the local SQLite LangGraph checkpoint store safely.

The command is dry-run by default.  It never touches PostgreSQL checkpoint
tables and only deletes checkpoint history after an operator opts into both a
retention count and ``--apply`` while the local backend is stopped.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


def _default_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "agent_checkpoints.db"


def _load_candidates(connection: sqlite3.Connection, *, keep_per_thread: int) -> list[tuple[str, str, str]]:
    """Return older checkpoints after preserving newest IDs per thread namespace.

    LangGraph's checkpoint IDs are time-sortable UUIDs, so descending lexical
    order preserves the newest state without decoding serializer payloads.
    """
    retained: dict[tuple[str, str], int] = defaultdict(int)
    candidates: list[tuple[str, str, str]] = []
    rows = connection.execute(
        """
        SELECT thread_id, checkpoint_ns, checkpoint_id
        FROM checkpoints
        ORDER BY thread_id ASC, checkpoint_ns ASC, checkpoint_id DESC
        """
    )
    for thread_id, namespace, checkpoint_id in rows:
        key = (str(thread_id), str(namespace))
        retained[key] += 1
        if retained[key] > keep_per_thread:
            candidates.append((str(thread_id), str(namespace), str(checkpoint_id)))
    return candidates


def _summary(connection: sqlite3.Connection) -> dict[str, int]:
    checkpoints = connection.execute("SELECT count(*) FROM checkpoints").fetchone()[0]
    writes = connection.execute("SELECT count(*) FROM writes").fetchone()[0]
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    page_count = connection.execute("PRAGMA page_count").fetchone()[0]
    return {
        "checkpoints": int(checkpoints),
        "writes": int(writes),
        "file_bytes": int(page_size) * int(page_count),
    }


def _delete(connection: sqlite3.Connection, candidates: list[tuple[str, str, str]]) -> tuple[int, int]:
    deleted_checkpoints = 0
    deleted_writes = 0
    for start in range(0, len(candidates), 250):
        batch = candidates[start : start + 250]
        with connection:
            for thread_id, namespace, checkpoint_id in batch:
                deleted_writes += connection.execute(
                    """
                    DELETE FROM writes
                    WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
                    """,
                    (thread_id, namespace, checkpoint_id),
                ).rowcount
                deleted_checkpoints += connection.execute(
                    """
                    DELETE FROM checkpoints
                    WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
                    """,
                    (thread_id, namespace, checkpoint_id),
                ).rowcount
    return deleted_checkpoints, deleted_writes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or compact local LangGraph SQLite checkpoints")
    parser.add_argument("--path", type=Path, default=_default_path(), help="SQLite checkpoint database path")
    parser.add_argument(
        "--keep-per-thread",
        type=int,
        required=True,
        help="number of newest checkpoints to preserve in each thread namespace",
    )
    parser.add_argument("--apply", action="store_true", help="delete identified history; dry-run is the default")
    parser.add_argument(
        "--vacuum-into",
        type=Path,
        help="write a compact replacement database after --apply; target must not exist",
    )
    args = parser.parse_args(argv)
    if args.keep_per_thread < 1:
        parser.error("--keep-per-thread must be at least 1")
    if args.vacuum_into and not args.apply:
        parser.error("--vacuum-into requires --apply")
    if args.vacuum_into and args.vacuum_into.exists():
        parser.error("--vacuum-into target already exists; refusing to overwrite it")
    if not args.path.is_file():
        parser.error(f"checkpoint database not found: {args.path}")

    # The command intentionally opens an existing database only.  Operators
    # must stop the backend first, so an active graph cannot write between the
    # retained-state calculation and deletion.
    connection = sqlite3.connect(f"file:{args.path.resolve()}?mode=rw", uri=True)
    try:
        before = _summary(connection)
        candidates = _load_candidates(connection, keep_per_thread=args.keep_per_thread)
        result: dict[str, object] = {
            "path": str(args.path.resolve()),
            "mode": "apply" if args.apply else "dry_run",
            "keep_per_thread": args.keep_per_thread,
            "before": before,
            "candidate_checkpoints": len(candidates),
        }
        if args.apply:
            checkpoints, writes = _delete(connection, candidates)
            result["deleted_checkpoints"] = checkpoints
            result["deleted_writes"] = writes
            if args.vacuum_into:
                args.vacuum_into.parent.mkdir(parents=True, exist_ok=True)
                connection.execute("VACUUM INTO ?", (str(args.vacuum_into.resolve()),))
                result["vacuum_output"] = str(args.vacuum_into.resolve())
            result["after"] = _summary(connection)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
