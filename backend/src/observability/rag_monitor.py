"""Run the RAG health monitor once or continuously."""
from __future__ import annotations

import argparse
import asyncio
import json

from src.observability.rag_metrics import monitor_once, worker_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate Agenora RAG health metrics")
    parser.add_argument("--once", action="store_true", help="print one JSON snapshot and exit")
    parser.add_argument("--fail-on-alert", action="store_true", help="exit 2 when alert thresholds fire")
    args = parser.parse_args(argv)
    if not args.once:
        asyncio.run(worker_main())
        return 0
    snapshot, status = asyncio.run(monitor_once(fail_on_alert=args.fail_on_alert))
    print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
