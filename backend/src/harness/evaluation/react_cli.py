"""CLI gate for deterministic ReAct runtime behavior cases."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.harness.evaluation.react_runtime import (
    ReactEvaluationError,
    assert_react_quality_gate,
    evaluate_react_cases,
    load_react_cases,
    report_json,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Agenora ReAct runtime behavior against a versioned golden set")
    parser.add_argument("--dataset", help="ReAct case JSONL path")
    parser.add_argument("--gate", help="JSON gate with dataset and max_failures")
    parser.add_argument("--report", help="write full JSON report (stdout when omitted)")
    parser.add_argument("--max-failures", type=int)
    return parser


def _load_gate(path: str) -> tuple[str, int]:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReactEvaluationError(f"{source}: invalid JSON") from exc
    if not isinstance(raw, dict):
        raise ReactEvaluationError(f"{source}: gate must be an object")
    dataset = str(raw.get("dataset") or "").strip()
    if not dataset:
        raise ReactEvaluationError(f"{source}: dataset is required")
    try:
        max_failures = int(raw.get("max_failures", 0))
    except (TypeError, ValueError) as exc:
        raise ReactEvaluationError(f"{source}: max_failures must be an integer") from exc
    return dataset, max(0, max_failures)


def _write_report(report: dict, path: str | None) -> None:
    output = report_json(report)
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report: dict | None = None
    try:
        gate_dataset, gate_max_failures = _load_gate(args.gate) if args.gate else ("", 0)
        dataset = args.dataset or gate_dataset
        if not dataset:
            raise ReactEvaluationError("--dataset or --gate with dataset is required")
        cases = load_react_cases(dataset)
        report = asyncio.run(evaluate_react_cases(cases))
        assert_react_quality_gate(
            report,
            max_failures=args.max_failures if args.max_failures is not None else gate_max_failures,
        )
        _write_report(report, args.report)
        return 0
    except ReactEvaluationError as exc:
        if report is not None:
            _write_report(report, args.report)
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
