"""Run the RAG health monitor once or continuously."""
from __future__ import annotations

import argparse
import asyncio
import json

import structlog

from src.bootstrap.database import initialize_database
from src.platform.observability.rag_metrics import build_rag_monitor_snapshot
from src.platform.persistence.database import get_session_factory
from src.settings import get_settings

log = structlog.get_logger()


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


async def monitor_once(*, fail_on_alert: bool = False) -> tuple[dict, int]:
    """Run one aggregation sweep after bootstrap has initialized the schema."""
    await initialize_database()
    factory = get_session_factory()
    async with factory() as session:
        snapshot = await build_rag_monitor_snapshot(session)
    for alert in snapshot["alerts"]:
        log.warning("rag_monitor_alert", **alert, window_hours=snapshot["window_hours"])
    return snapshot, (2 if fail_on_alert and snapshot["alerts"] else 0)


async def worker_main() -> None:
    """Continuous monitoring loop; Compose forwards logs to its collector."""
    settings = get_settings()
    interval = _bounded_int(
        settings.rag_monitor_interval_seconds, default=300, minimum=30, maximum=86_400
    )
    while True:
        try:
            snapshot, _ = await monitor_once()
            log.info(
                "rag_monitor_snapshot",
                status=snapshot["status"],
                metrics=snapshot["metrics"],
                alert_count=len(snapshot["alerts"]),
            )
        except Exception as exc:  # noqa: BLE001 - monitor must self-heal on transient DB errors
            log.exception("rag_monitor_failed", error=str(exc))
        await asyncio.sleep(interval)


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
