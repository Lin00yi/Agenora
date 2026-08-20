"""Knowledge evaluation use cases: config, live regression, and replay."""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.capabilities.knowledge.domain.models import KB, KbEvalConfig, KbEvalRun
from src.evals.metrics import (
    EvaluationGateError,
    RAGGoldenCase,
    assert_quality_gate,
    collapse_retrieved_to_documents,
    evaluate,
    parse_cases_jsonl,
    parse_gate_json,
    parse_predictions_jsonl,
    search_overfetch_limit,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
EVAL_RUNS_BASE = _BACKEND_ROOT / "data" / "eval_runs"
CONFIG_DIR = _BACKEND_ROOT / "config"
MAX_GOLDEN_CASES = 100
MAX_RETRIEVAL_JSONL_BYTES = 5 * 1024 * 1024
ROOGOO_TEMPLATE_ID = "roogoo"

_TEMPLATES: dict[str, dict[str, str]] = {
    ROOGOO_TEMPLATE_ID: {
        "name": "Roogoo 帮助中心",
        "golden_set": "rag_eval_roogoo.jsonl",
        "gate": "rag_eval_roogoo_gate.json",
    }
}


class _HasIdQuery(Protocol):
    id: str
    query: str


def golden_set_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def list_eval_templates() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for template_id, meta in _TEMPLATES.items():
        golden_path = CONFIG_DIR / meta["golden_set"]
        gate_path = CONFIG_DIR / meta["gate"]
        if not golden_path.is_file():
            continue
        cases = parse_cases_jsonl(golden_path.read_text(encoding="utf-8"), source=str(golden_path))
        gate: dict[str, Any] = {}
        if gate_path.is_file():
            gate = parse_gate_json(gate_path.read_text(encoding="utf-8"), source=str(gate_path))
        out.append(
            {
                "id": template_id,
                "name": meta["name"],
                "case_count": len(cases),
                "k": gate.get("k", 3),
            }
        )
    return out


def load_template(template_id: str) -> tuple[str, str]:
    meta = _TEMPLATES.get(template_id)
    if meta is None:
        raise EvaluationGateError(f"unknown eval template: {template_id}")
    golden_path = CONFIG_DIR / meta["golden_set"]
    gate_path = CONFIG_DIR / meta["gate"]
    if not golden_path.is_file():
        raise EvaluationGateError(f"template {template_id}: golden set file missing")
    golden = golden_path.read_text(encoding="utf-8")
    gate = gate_path.read_text(encoding="utf-8") if gate_path.is_file() else "{}"
    parse_cases_jsonl(golden, source=str(golden_path))
    if gate.strip():
        parse_gate_json(gate, source=str(gate_path))
    return golden, gate


def parse_eval_config(golden_set_jsonl: str, gate_json: str = "") -> tuple[list[RAGGoldenCase], dict[str, Any]]:
    cases = parse_cases_jsonl(golden_set_jsonl, source="golden-set")
    if len(cases) > MAX_GOLDEN_CASES:
        raise EvaluationGateError(f"golden set has {len(cases)} cases; max is {MAX_GOLDEN_CASES}")
    gate: dict[str, Any] = {
        "dataset": "",
        "kb_id": "",
        "k": 3,
        "minimums": {
            "recall_at_k": None,
            "mrr": None,
            "ndcg_at_k": None,
            "citation_precision": None,
        },
        "baseline": {},
        "notes": "",
    }
    if gate_json.strip():
        gate = parse_gate_json(gate_json, source="gate")
    return cases, gate


def config_public_dict(config: KbEvalConfig | None) -> dict[str, Any]:
    if config is None or not (config.golden_set_jsonl or "").strip():
        return {
            "configured": False,
            "case_count": 0,
            "k": 3,
            "golden_set_hash": None,
            "minimums": {},
            "baseline": {},
            "notes": "",
            "cases": [],
            "updated_at": None,
        }
    cases, gate = parse_eval_config(config.golden_set_jsonl, config.gate_json)
    return {
        "configured": True,
        "case_count": len(cases),
        "k": gate.get("k", 3),
        "golden_set_hash": config.golden_set_hash,
        "minimums": gate.get("minimums") or {},
        "baseline": gate.get("baseline") or {},
        "notes": gate.get("notes") or "",
        "cases": [
            {
                "id": case.id,
                "query": case.query,
                "tags": list(case.tags),
                "expected_document_ids": sorted(case.expected_document_ids),
            }
            for case in cases
        ],
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


async def get_eval_config(session: AsyncSession, kb_id: str) -> KbEvalConfig | None:
    return await session.get(KbEvalConfig, kb_id)


async def upsert_eval_config(
    session: AsyncSession,
    kb: KB,
    *,
    golden_set_jsonl: str,
    gate_json: str = "",
) -> KbEvalConfig:
    parse_eval_config(golden_set_jsonl, gate_json)
    config = await session.get(KbEvalConfig, kb.id)
    digest = golden_set_hash(golden_set_jsonl)
    if config is None:
        config = KbEvalConfig(
            kb_id=kb.id,
            golden_set_jsonl=golden_set_jsonl,
            gate_json=gate_json,
            golden_set_hash=digest,
        )
        session.add(config)
    else:
        config.golden_set_jsonl = golden_set_jsonl
        config.gate_json = gate_json
        config.golden_set_hash = digest
    await session.commit()
    await session.refresh(config)
    return config


def _collapse_tool_rows(rows: list[Any], *, k: int) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("doc_id") or item.get("document_id")
        if not doc_id:
            continue
        mapped.append(
            {
                "document_id": doc_id,
                "filename": item.get("filename"),
                "score": item.get("score"),
            }
        )
    return collapse_retrieved_to_documents(mapped, k=k)


async def retrieve_predictions(
    session: AsyncSession,
    kb: KB,
    cases: Iterable[_HasIdQuery],
    *,
    k: int,
) -> list[dict[str, Any]]:
    """Run in-process KB search for golden queries. Returns metadata only."""
    from src.capabilities.knowledge.application.configuration import resolve_kb_embedding, resolve_kb_reranker
    from src.tools.kb_search import KBSearchTool

    owner = await session.get(User, kb.user_id)
    tool = KBSearchTool(
        kb=kb,
        embedding_cfg=resolve_kb_embedding(kb, owner),
        reranker_cfg=resolve_kb_reranker(kb, owner),
    )
    fetch_limit = search_overfetch_limit(k)
    predictions: list[dict[str, Any]] = []
    for case in cases:
        result = await tool.execute(case.query, limit=fetch_limit)
        raw = result.raw if isinstance(result.raw, dict) else {}
        rows = raw.get("results") if isinstance(raw.get("results"), list) else []
        predictions.append(
            {
                "id": case.id,
                "retrieved": _collapse_tool_rows(rows, k=k),
                "error": result.error,
            }
        )
    return predictions


def predictions_from_rows(rows: list[dict[str, Any]], *, k: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("id") or "").strip()
        if not case_id:
            continue
        if row.get("error"):
            raise EvaluationGateError(f"case {case_id}: retrieval failed: {row['error']}")
        out[case_id] = {
            "id": case_id,
            "retrieved": collapse_retrieved_to_documents(list(row.get("retrieved") or []), k=k),
        }
        if "citations" in row:
            out[case_id]["citations"] = row.get("citations")
    return out


def serialize_predictions(predictions: dict[str, dict[str, Any]]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in predictions.values()
    )


def score_report(
    cases: list[RAGGoldenCase],
    predictions: dict[str, dict[str, Any]],
    gate: dict[str, Any],
) -> tuple[dict[str, Any], bool, str | None]:
    k = int(gate.get("k") or 3)
    report = evaluate(cases, predictions, k=k)
    minimums = gate.get("minimums") if isinstance(gate.get("minimums"), dict) else {}
    gate_error: str | None = None
    passed = True
    try:
        assert_quality_gate(
            report,
            min_recall_at_k=minimums.get("recall_at_k"),
            min_mrr=minimums.get("mrr"),
            min_ndcg_at_k=minimums.get("ndcg_at_k"),
            min_citation_precision=minimums.get("citation_precision"),
            max_missing_cases=0,
        )
    except EvaluationGateError as exc:
        passed = False
        gate_error = str(exc)
    report["gate_passed"] = passed
    if gate_error:
        report["gate_error"] = gate_error
    return report, passed, gate_error


def _write_retrieval_jsonl(kb_id: str, run_id: str, body: str) -> str:
    relative = f"{kb_id}/{run_id}.jsonl"
    target = EVAL_RUNS_BASE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return relative


def delete_eval_run_files(kb_id: str) -> None:
    base = EVAL_RUNS_BASE / kb_id
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)


async def save_eval_run(
    session: AsyncSession,
    kb: KB,
    *,
    run_type: str,
    golden_set_hash_value: str,
    k: int,
    report: dict[str, Any],
    gate_passed: bool,
    predictions: dict[str, dict[str, Any]] | None,
    created_by: str,
) -> KbEvalRun:
    run_id = str(uuid.uuid4())
    relative = ""
    if predictions:
        relative = _write_retrieval_jsonl(kb.id, run_id, serialize_predictions(predictions))
    run = KbEvalRun(
        id=run_id,
        kb_id=kb.id,
        run_type=run_type,
        golden_set_hash=golden_set_hash_value,
        k=k,
        report_json=json.dumps(report, ensure_ascii=False, sort_keys=True),
        gate_passed=gate_passed,
        retrieval_jsonl_path=relative,
        created_by=created_by,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def run_regression(
    session: AsyncSession,
    kb: KB,
    *,
    created_by: str,
) -> KbEvalRun:
    config = await get_eval_config(session, kb.id)
    if config is None or not (config.golden_set_jsonl or "").strip():
        raise EvaluationGateError("golden set is not configured for this knowledge base")
    cases, gate = parse_eval_config(config.golden_set_jsonl, config.gate_json)
    k = int(gate.get("k") or 3)
    rows = await retrieve_predictions(session, kb, cases, k=k)
    predictions = predictions_from_rows(rows, k=k)
    report, passed, _error = score_report(cases, predictions, gate)
    return await save_eval_run(
        session,
        kb,
        run_type="regression",
        golden_set_hash_value=config.golden_set_hash,
        k=k,
        report=report,
        gate_passed=passed,
        predictions=predictions,
        created_by=created_by,
    )


def load_run_predictions(run: KbEvalRun) -> dict[str, dict[str, Any]]:
    if not run.retrieval_jsonl_path:
        raise EvaluationGateError("this run has no stored retrieval.jsonl")
    path = EVAL_RUNS_BASE / run.retrieval_jsonl_path
    if not path.is_file():
        raise EvaluationGateError("stored retrieval.jsonl is missing")
    return parse_predictions_jsonl(path.read_text(encoding="utf-8"), source=str(path))


async def replay_predictions(
    session: AsyncSession,
    kb: KB,
    predictions: dict[str, dict[str, Any]],
    *,
    created_by: str,
) -> KbEvalRun:
    config = await get_eval_config(session, kb.id)
    if config is None or not (config.golden_set_jsonl or "").strip():
        raise EvaluationGateError("golden set is not configured for this knowledge base")
    cases, gate = parse_eval_config(config.golden_set_jsonl, config.gate_json)
    k = int(gate.get("k") or 3)
    collapsed = predictions_from_rows(
        [{"id": case_id, **row} for case_id, row in predictions.items()],
        k=k,
    )
    report, passed, _error = score_report(cases, collapsed, gate)
    return await save_eval_run(
        session,
        kb,
        run_type="replay",
        golden_set_hash_value=config.golden_set_hash,
        k=k,
        report=report,
        gate_passed=passed,
        predictions=collapsed,
        created_by=created_by,
    )


async def list_eval_runs(
    session: AsyncSession,
    kb_id: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[KbEvalRun], int]:
    from sqlalchemy import func

    total = int(
        (
            await session.execute(
                select(func.count()).select_from(KbEvalRun).where(KbEvalRun.kb_id == kb_id)
            )
        ).scalar_one()
    )
    rows = list(
        (
            await session.execute(
                select(KbEvalRun)
                .where(KbEvalRun.kb_id == kb_id)
                .order_by(KbEvalRun.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )
    return rows, total


class EvaluationInputError(ValueError):
    """Raised when an API caller has not supplied a usable golden set."""


def list_templates() -> list[dict[str, Any]]:
    """HTTP-facing template listing without coupling delivery to domain names."""
    return list_eval_templates()


async def public_config(session: AsyncSession, kb_id: str) -> dict[str, Any]:
    return config_public_dict(await get_eval_config(session, kb_id))


async def save_config(
    session: AsyncSession,
    kb: KB,
    *,
    golden_set_jsonl: str | None,
    gate_json: str | None,
    template: str | None,
) -> dict[str, Any]:
    if template:
        golden_set_jsonl, gate_json = load_template(template)
    else:
        existing = await get_eval_config(session, kb.id)
        golden_set_jsonl = golden_set_jsonl if golden_set_jsonl is not None else (
            existing.golden_set_jsonl if existing else ""
        )
        gate_json = gate_json if gate_json is not None else (
            existing.gate_json if existing else ""
        )
        if not (golden_set_jsonl or "").strip():
            raise EvaluationInputError("golden_set_jsonl or template is required")
    config = await upsert_eval_config(
        session,
        kb,
        golden_set_jsonl=golden_set_jsonl or "",
        gate_json=gate_json or "",
    )
    return config_public_dict(config)


async def run_regression_public(
    session: AsyncSession, kb: KB, *, created_by: str
) -> dict[str, Any]:
    run = await run_regression(session, kb, created_by=created_by)
    return run.to_public_dict(include_report=True)


async def list_runs(
    session: AsyncSession, kb_id: str, *, limit: int, offset: int
) -> dict[str, Any]:
    rows, total = await list_eval_runs(session, kb_id, limit=limit, offset=offset)
    return {"total": total, "limit": limit, "offset": offset, "runs": [row.to_public_dict() for row in rows]}


def max_predictions_bytes() -> int:
    return MAX_RETRIEVAL_JSONL_BYTES


def parse_predictions(raw: bytes) -> dict[str, dict[str, Any]]:
    return parse_predictions_jsonl(raw.decode("utf-8"), source="retrieval.jsonl")


def predictions_from_run(run: KbEvalRun) -> dict[str, dict[str, Any]]:
    return load_run_predictions(run)


async def replay(
    session: AsyncSession,
    kb: KB,
    predictions: dict[str, dict[str, Any]],
    *,
    created_by: str,
) -> dict[str, Any]:
    run = await replay_predictions(session, kb, predictions, created_by=created_by)
    return run.to_public_dict(include_report=True)


def delete_run_files(kb_id: str) -> None:
    """Remove derived artifacts after the KB itself has been deleted."""
    delete_eval_run_files(kb_id)
