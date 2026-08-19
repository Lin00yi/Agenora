"""CLI for live or recorded golden-set retrieval evaluation.

Examples:
  python -m src.evals.cli --dataset config/rag_eval_cases.jsonl --results out.jsonl
  python -m src.evals.cli --dataset config/rag_eval_cases.jsonl --kb-id ... --write-results out.jsonl --min-recall-at-k .8
  python -m src.evals.cli --gate config/rag_eval_roogoo_gate.json --api-base-url http://127.0.0.1:8000 --api-token ...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from src.evals.metrics import (
    EvaluationGateError,
    assert_quality_gate,
    collapse_retrieved_to_documents,
    evaluate,
    load_cases,
    load_gate,
    load_predictions,
    report_json,
    search_overfetch_limit,
)


async def _live_predictions(cases, *, kb_id: str, limit: int) -> dict[str, dict[str, Any]]:
    from src.auth.models import User
    from src.storage.database import get_session_factory, init_db
    from src.kb.models import KB
    from src.settings_user.kb_resolvers import resolve_kb_embedding, resolve_kb_reranker
    from src.tools.kb_search import KBSearchTool

    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        kb = await session.get(KB, kb_id)
        if kb is None:
            raise EvaluationGateError(f"knowledge base not found: {kb_id}")
        owner = await session.get(User, kb.user_id)
        tool = KBSearchTool(
            kb=kb,
            embedding_cfg=resolve_kb_embedding(kb, owner),
            reranker_cfg=resolve_kb_reranker(kb, owner),
        )
        out: dict[str, dict[str, Any]] = {}
        fetch_limit = search_overfetch_limit(limit)
        for case in cases:
            result = await tool.execute(case.query, limit=fetch_limit)
            if result.error:
                raise EvaluationGateError(f"case {case.id}: retrieval failed: {result.error}")
            raw = result.raw if isinstance(result.raw, dict) else {}
            out[case.id] = {
                "id": case.id,
                "retrieved": collapse_retrieved_to_documents(list(raw.get("results") or []), k=limit),
            }
        return out


async def _service_predictions(
    cases,
    *,
    kb_id: str,
    limit: int,
    api_base_url: str,
    api_token: str,
) -> dict[str, dict[str, Any]]:
    """Use the running backend for Milvus Lite-safe live evaluation."""
    base_url = api_base_url.rstrip("/")
    try:
        # A local evaluation service must not be routed through a corporate
        # proxy/VPN (which commonly returns 502 for 127.0.0.1). Operators who
        # need a remote proxy can pass the proxy address as api_base_url.
        async with httpx.AsyncClient(timeout=90.0, trust_env=False) as client:
            response = await client.post(
                f"{base_url}/api/admin/rag/evaluate-retrieval",
                headers={"Authorization": f"Bearer {api_token}"},
                json={
                    "kb_id": kb_id,
                    "limit": search_overfetch_limit(limit),
                    "cases": [{"id": case.id, "query": case.query} for case in cases],
                },
            )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EvaluationGateError(f"service evaluation request failed: {exc}") from exc
    payload = response.json()
    rows = payload.get("predictions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise EvaluationGateError("service evaluation response has no predictions")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        case_id = str(row.get("id") or "").strip()
        if not case_id:
            continue
        if row.get("error"):
            raise EvaluationGateError(f"case {case_id}: retrieval failed: {row['error']}")
        out[case_id] = {
            "id": case_id,
            "retrieved": collapse_retrieved_to_documents(list(row.get("retrieved") or []), k=limit),
        }
    return out


def _write_predictions(path: str | Path, predictions: dict[str, dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in predictions.values()),
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Agenora RAG retrieval against a versioned golden set")
    parser.add_argument("--dataset", help="golden-case JSONL path")
    parser.add_argument("--gate", help="JSON gate with dataset, kb_id, k, and minimums")
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--results", help="recorded retrieval/answer JSONL path")
    source.add_argument("--kb-id", help="run live KB retrieval for every case")
    parser.add_argument("--write-results", help="write live retrieval output JSONL")
    parser.add_argument(
        "--api-base-url",
        help="use a running admin API for live retrieval (required with --api-token)",
    )
    parser.add_argument("--api-token", help="administrator Bearer token for --api-base-url")
    parser.add_argument("--report", help="write full JSON report (stdout when omitted)")
    parser.add_argument("--k", type=int)
    parser.add_argument("--min-recall-at-k", type=float)
    parser.add_argument("--min-mrr", type=float)
    parser.add_argument("--min-ndcg-at-k", type=float)
    parser.add_argument("--min-citation-precision", type=float)
    parser.add_argument("--max-missing-cases", type=int, default=0)
    return parser


def _emit_report(report: dict[str, Any], path: str | None) -> None:
    output = report_json(report)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report: dict[str, Any] | None = None
    try:
        gate = load_gate(args.gate) if args.gate else {}
        dataset = args.dataset or str(gate.get("dataset") or "")
        if not dataset:
            raise EvaluationGateError("--dataset or --gate with dataset is required")
        k = args.k if args.k is not None else int(gate.get("k") or 3)
        kb_id = args.kb_id or str(gate.get("kb_id") or "")
        minimums = gate.get("minimums") if isinstance(gate.get("minimums"), dict) else {}
        cases = load_cases(dataset)
        if args.results:
            predictions = load_predictions(args.results)
        else:
            if not kb_id:
                raise EvaluationGateError("--kb-id or --gate with kb_id is required for live evaluation")
            if bool(args.api_base_url) != bool(args.api_token):
                raise EvaluationGateError("--api-base-url and --api-token must be provided together")
            if args.api_base_url:
                predictions = asyncio.run(
                    _service_predictions(
                        cases,
                        kb_id=kb_id,
                        limit=k,
                        api_base_url=args.api_base_url,
                        api_token=args.api_token,
                    )
                )
            else:
                predictions = asyncio.run(_live_predictions(cases, kb_id=kb_id, limit=k))
            if args.write_results:
                _write_predictions(args.write_results, predictions)
        report = evaluate(cases, predictions, k=k)
        assert_quality_gate(
            report,
            min_recall_at_k=args.min_recall_at_k if args.min_recall_at_k is not None else minimums.get("recall_at_k"),
            min_mrr=args.min_mrr if args.min_mrr is not None else minimums.get("mrr"),
            min_ndcg_at_k=args.min_ndcg_at_k if args.min_ndcg_at_k is not None else minimums.get("ndcg_at_k"),
            min_citation_precision=(
                args.min_citation_precision
                if args.min_citation_precision is not None
                else minimums.get("citation_precision")
            ),
            max_missing_cases=args.max_missing_cases,
        )
        _emit_report(report, args.report)
        return 0
    except EvaluationGateError as exc:
        if report is not None:
            _emit_report(report, args.report)
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
