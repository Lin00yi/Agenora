"""Explicit CLI for the paid, real-Provider ReAct tool-selection baseline."""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace
from pathlib import Path

from src.capabilities.settings.domain.models import resolve_system_llm
from src.harness.evaluation.live_tool_selection import (
    LiveToolSelectionError,
    assert_live_tool_selection_gate,
    evaluate_live_tool_selection,
    load_live_tool_cases,
    report_json,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run paid live Provider tool-selection baseline")
    parser.add_argument("--dataset", default="config/react_live_tool_cases.jsonl")
    parser.add_argument("--model", help="override the configured default model for this run")
    parser.add_argument("--max-failures", type=int, default=0)
    parser.add_argument("--max-total-cost-usd", type=float)
    parser.add_argument("--report", help="write full JSON report (stdout when omitted)")
    parser.add_argument("--live", action="store_true", help="required acknowledgement before any Provider request")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.live:
        print("refusing Provider request: pass --live after reviewing cost and configured credentials", file=sys.stderr)
        return 2
    report: dict | None = None
    try:
        cfg = resolve_system_llm()
        if cfg is None:
            raise LiveToolSelectionError("configured system LLM credentials are required")
        if args.model:
            cfg = replace(cfg, default_model=args.model, complex_model=args.model, complex_enabled=False)
        report = asyncio.run(evaluate_live_tool_selection(load_live_tool_cases(args.dataset), llm_cfg=cfg))
        assert_live_tool_selection_gate(
            report,
            max_failures=args.max_failures,
            max_total_cost_usd=args.max_total_cost_usd,
        )
        output = report_json(report)
        if args.report:
            Path(args.report).write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
        return 0
    except LiveToolSelectionError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
