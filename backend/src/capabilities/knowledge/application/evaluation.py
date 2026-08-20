"""Knowledge evaluation use cases, independent from FastAPI request objects."""
from __future__ import annotations

from typing import Any


class EvaluationInputError(ValueError):
    pass


def list_templates() -> list[str]:
    from src.kb.eval_service import list_eval_templates

    return list_eval_templates()


async def public_config(session: Any, kb_id: str) -> dict[str, Any]:
    from src.kb.eval_service import config_public_dict, get_eval_config

    return config_public_dict(await get_eval_config(session, kb_id))


async def save_config(
    session: Any,
    kb: Any,
    *,
    golden_set_jsonl: str | None,
    gate_json: str | None,
    template: str | None,
) -> dict[str, Any]:
    from src.kb.eval_service import (
        config_public_dict,
        get_eval_config,
        load_template,
        upsert_eval_config,
    )

    if template:
        golden_set_jsonl, gate_json = load_template(template)
    else:
        existing = await get_eval_config(session, kb.id)
        golden_set_jsonl = golden_set_jsonl if golden_set_jsonl is not None else (
            existing.golden_set_jsonl if existing else ""
        )
        gate_json = gate_json if gate_json is not None else (existing.gate_json if existing else "")
        if not (golden_set_jsonl or "").strip():
            raise EvaluationInputError("golden_set_jsonl or template is required")
    config = await upsert_eval_config(
        session,
        kb,
        golden_set_jsonl=golden_set_jsonl or "",
        gate_json=gate_json or "",
    )
    return config_public_dict(config)


async def run_regression(session: Any, kb: Any, *, created_by: str) -> dict[str, Any]:
    from src.kb.eval_service import run_regression as _run_regression

    run = await _run_regression(session, kb, created_by=created_by)
    return run.to_public_dict(include_report=True)


async def list_runs(session: Any, kb_id: str, *, limit: int, offset: int) -> dict[str, Any]:
    from src.kb.eval_service import list_eval_runs

    rows, total = await list_eval_runs(session, kb_id, limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [row.to_public_dict() for row in rows],
    }


def max_predictions_bytes() -> int:
    from src.kb.eval_service import MAX_RETRIEVAL_JSONL_BYTES

    return MAX_RETRIEVAL_JSONL_BYTES


def parse_predictions(raw: bytes) -> Any:
    from src.kb.eval_service import parse_predictions_jsonl

    return parse_predictions_jsonl(raw.decode("utf-8"), source="retrieval.jsonl")


def predictions_from_run(run: Any) -> Any:
    from src.kb.eval_service import load_run_predictions

    return load_run_predictions(run)


async def replay(session: Any, kb: Any, predictions: Any, *, created_by: str) -> dict[str, Any]:
    from src.kb.eval_service import replay_predictions

    run = await replay_predictions(session, kb, predictions, created_by=created_by)
    return run.to_public_dict(include_report=True)


def delete_run_files(kb_id: str) -> None:
    """Remove derived evaluation artifacts after the KB itself is deleted."""
    from src.kb.eval_service import delete_eval_run_files

    delete_eval_run_files(kb_id)
