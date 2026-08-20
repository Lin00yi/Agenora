"""Inspect or compact the local SQLite LangGraph checkpoint store safely.

The command is dry-run by default.  It never touches PostgreSQL checkpoint
tables and only deletes checkpoint history after an operator opts into both a
retention count and ``--apply`` while the local backend is stopped.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from shutil import disk_usage


CheckpointKey = tuple[str, str, str]
CandidateBatchHandler = Callable[[list[CheckpointKey]], None]

_SCAN_BATCH_SIZE = 1_000
_DELETE_BATCH_SIZE = 250


def _default_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "agent_checkpoints.db"


def _scan_candidates(
    connection: sqlite3.Connection,
    *,
    keep_per_thread: int,
    on_batch: CandidateBatchHandler | None = None,
) -> tuple[int, int]:
    """Visit old checkpoints without retaining the full candidate set in memory.

    LangGraph's checkpoint IDs are time-sortable UUIDs, so descending lexical
    order preserves the newest state without decoding serializer payloads.  A
    checkpoint database can be many gigabytes, so this deliberately uses
    keyset pagination instead of ``fetchall()`` or an in-memory candidate list.

    ``on_batch`` is called only after a SELECT result has been fully
    materialized.  This lets apply mode delete a small batch safely without
    mutating a table beneath a live SQLite cursor.
    """
    last_key: CheckpointKey | None = None
    current_namespace: tuple[str, str] | None = None
    retained_in_namespace = 0
    checkpoint_count = 0
    candidate_count = 0

    while True:
        if last_key is None:
            rows = connection.execute(
                """
                SELECT thread_id, checkpoint_ns, checkpoint_id
                FROM checkpoints
                ORDER BY thread_id ASC, checkpoint_ns ASC, checkpoint_id DESC
                LIMIT ?
                """,
                (_SCAN_BATCH_SIZE,),
            ).fetchall()
        else:
            thread_id, namespace, checkpoint_id = last_key
            rows = connection.execute(
                """
                SELECT thread_id, checkpoint_ns, checkpoint_id
                FROM checkpoints
                WHERE thread_id > ?
                   OR (thread_id = ? AND checkpoint_ns > ?)
                   OR (
                       thread_id = ?
                       AND checkpoint_ns = ?
                       AND checkpoint_id < ?
                   )
                ORDER BY thread_id ASC, checkpoint_ns ASC, checkpoint_id DESC
                LIMIT ?
                """,
                (thread_id, thread_id, namespace, thread_id, namespace, checkpoint_id, _SCAN_BATCH_SIZE),
            ).fetchall()
        if not rows:
            break

        candidates: list[CheckpointKey] = []
        for raw_thread_id, raw_namespace, raw_checkpoint_id in rows:
            key = (str(raw_thread_id), str(raw_namespace), str(raw_checkpoint_id))
            namespace_key = key[:2]
            if namespace_key != current_namespace:
                current_namespace = namespace_key
                retained_in_namespace = 0
            retained_in_namespace += 1
            checkpoint_count += 1
            if retained_in_namespace > keep_per_thread:
                candidates.append(key)

        candidate_count += len(candidates)
        if candidates and on_batch is not None:
            for start in range(0, len(candidates), _DELETE_BATCH_SIZE):
                on_batch(candidates[start : start + _DELETE_BATCH_SIZE])
        last_key = (str(rows[-1][0]), str(rows[-1][1]), str(rows[-1][2]))

    return checkpoint_count, candidate_count


def _file_summary(connection: sqlite3.Connection) -> dict[str, int]:
    """Return O(1) file metadata; full table counts are too costly for large DBs."""
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    page_count = connection.execute("PRAGMA page_count").fetchone()[0]
    return {
        "file_bytes": int(page_size) * int(page_count),
    }


def _delete(connection: sqlite3.Connection, candidates: list[CheckpointKey]) -> tuple[int, int]:
    deleted_checkpoints = 0
    deleted_writes = 0
    with connection:
        for thread_id, namespace, checkpoint_id in candidates:
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


def _existing_parent(path: Path) -> Path:
    """Find the existing directory whose filesystem will host ``path``."""
    parent = path.expanduser().resolve().parent
    while not parent.exists():
        if parent == parent.parent:
            raise ValueError(f"cannot find an existing parent for {path}")
        parent = parent.parent
    return parent


def _require_vacuum_space(*, target: Path, source_bytes: int) -> None:
    """Fail before deletion when the compact-copy target cannot be created.

    SQLite cannot accurately predict the post-retention database size without
    first deleting rows.  Reserve 110% of the original size conservatively so
    ``VACUUM INTO`` cannot strand an operator with a partially written copy.
    A different mounted volume is the practical path when the source volume is
    already nearly full.
    """
    available = disk_usage(_existing_parent(target)).free
    required = int(source_bytes * 1.10)
    if available < required:
        raise ValueError(
            "insufficient free space for --vacuum-into: "
            f"available={available} bytes, conservative_required={required} bytes. "
            "Choose a path on a volume with enough free space."
        )


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
        file_summary = _file_summary(connection)
        if args.vacuum_into:
            try:
                _require_vacuum_space(target=args.vacuum_into, source_bytes=file_summary["file_bytes"])
            except ValueError as exc:
                parser.error(str(exc))

        deleted_checkpoints = 0
        deleted_writes = 0

        def delete_batch(candidates: list[CheckpointKey]) -> None:
            nonlocal deleted_checkpoints, deleted_writes
            checkpoints, writes = _delete(connection, candidates)
            deleted_checkpoints += checkpoints
            deleted_writes += writes

        checkpoint_count, candidate_count = _scan_candidates(
            connection,
            keep_per_thread=args.keep_per_thread,
            on_batch=delete_batch if args.apply else None,
        )
        before = {**file_summary, "checkpoints": checkpoint_count}
        result: dict[str, object] = {
            "path": str(args.path.resolve()),
            "mode": "apply" if args.apply else "dry_run",
            "keep_per_thread": args.keep_per_thread,
            "before": before,
            "candidate_checkpoints": candidate_count,
        }
        if args.apply:
            result["deleted_checkpoints"] = deleted_checkpoints
            result["deleted_writes"] = deleted_writes
            if args.vacuum_into:
                args.vacuum_into.parent.mkdir(parents=True, exist_ok=True)
                connection.execute("VACUUM INTO ?", (str(args.vacuum_into.resolve()),))
                result["vacuum_output"] = str(args.vacuum_into.resolve())
            result["after"] = {
                "file_bytes": _file_summary(connection)["file_bytes"],
                "checkpoints": checkpoint_count - deleted_checkpoints,
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
