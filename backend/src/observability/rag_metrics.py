"""Aggregate privacy-preserving, operational RAG health metrics from traces."""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.observability.models import Observation
from src.settings import Settings, get_settings

log = structlog.get_logger()

_RAG_TOOLS = {"search_kb": "kb", "search_kg": "kg"}


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _bounded_rate(value: object, *, default: float) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _alert(code: str, severity: str, message: str, *, value: float | int, threshold: float | int) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "value": value,
        "threshold": threshold,
    }


async def build_rag_monitor_snapshot(
    session: AsyncSession,
    *,
    hours: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return bounded-window operational RAG metrics and deterministic alerts.

    Only stable identifiers and tool metadata are read: document/chunk text and
    user prompts never leave the trace privacy boundary for this aggregation.
    """
    current = settings or get_settings()
    window_hours = _bounded_int(
        hours if hours is not None else current.rag_monitor_window_hours,
        default=24,
        minimum=1,
        maximum=24 * 31,
    )
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = list(
        (
            await session.execute(
                select(Observation)
                .where(
                    Observation.name.in_(tuple(_RAG_TOOLS)),
                    Observation.started_at >= cutoff,
                )
                .order_by(Observation.started_at.desc())
            )
        ).scalars()
    )

    latencies: list[int] = []
    top_scores: list[float] = []
    source_calls = {"kb": 0, "kg": 0}
    retrieval_trace_ids: set[str] = set()
    error_calls = 0
    empty_calls = 0
    measurable_empty_calls = 0

    for row in rows:
        source = _RAG_TOOLS[row.name]
        source_calls[source] += 1
        retrieval_trace_ids.add(row.trace_id)
        if row.duration_ms is not None:
            latencies.append(max(0, int(row.duration_ms)))
        if row.status != "ok":
            error_calls += 1
        metadata = row.metadata_dict()
        rag = metadata.get("rag") if isinstance(metadata.get("rag"), dict) else {}
        result_count = _number(rag.get("result_count"))
        if result_count is not None:
            measurable_empty_calls += 1
            if result_count <= 0 and row.status == "ok":
                empty_calls += 1
        score = _number(rag.get("max_score"))
        if score is not None:
            top_scores.append(score)

    total = len(rows)
    error_rate = error_calls / total if total else 0.0
    empty_rate = empty_calls / measurable_empty_calls if measurable_empty_calls else None
    avg_top_score = sum(top_scores) / len(top_scores) if top_scores else None
    p95_latency = _percentile(latencies, 0.95)
    min_calls = _bounded_int(current.rag_monitor_min_calls, default=20, minimum=1, maximum=100_000)
    alerts: list[dict] = []
    if total >= min_calls:
        max_error = _bounded_rate(current.rag_monitor_max_error_rate, default=0.05)
        max_empty = _bounded_rate(current.rag_monitor_max_empty_rate, default=0.45)
        max_latency = _bounded_int(
            current.rag_monitor_max_p95_latency_ms, default=5000, minimum=1, maximum=300_000
        )
        min_score = _bounded_rate(current.rag_monitor_min_avg_top_score, default=0.50)
        if error_rate > max_error:
            alerts.append(_alert("rag_error_rate", "critical", "RAG 工具错误率超过阈值", value=error_rate, threshold=max_error))
        if empty_rate is not None and empty_rate > max_empty:
            alerts.append(_alert("rag_empty_rate", "warning", "RAG 空检索率超过阈值", value=empty_rate, threshold=max_empty))
        if p95_latency is not None and p95_latency > max_latency:
            alerts.append(_alert("rag_p95_latency", "warning", "RAG P95 检索延迟超过阈值", value=p95_latency, threshold=max_latency))
        if avg_top_score is not None and avg_top_score < min_score:
            alerts.append(_alert("rag_low_top_score", "warning", "RAG 平均最高相关度低于阈值", value=avg_top_score, threshold=min_score))

    return {
        "window_hours": window_hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_sufficient": total >= min_calls,
        "min_calls": min_calls,
        "status": "alert" if alerts else "healthy",
        "alerts": alerts,
        "metrics": {
            "retrieval_calls": total,
            "retrieval_traces": len(retrieval_trace_ids),
            "kb_calls": source_calls["kb"],
            "kg_calls": source_calls["kg"],
            "error_calls": error_calls,
            "error_rate": error_rate,
            "measurable_empty_calls": measurable_empty_calls,
            "empty_calls": empty_calls,
            "empty_rate": empty_rate,
            "p95_latency_ms": p95_latency,
            "avg_top_score": avg_top_score,
        },
    }


async def monitor_once(*, fail_on_alert: bool = False) -> tuple[dict[str, Any], int]:
    """Run one aggregation sweep for a cron job, CLI, or Docker worker."""
    from src.infra.database import get_session_factory, init_db

    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        snapshot = await build_rag_monitor_snapshot(session)
    for alert in snapshot["alerts"]:
        log.warning("rag_monitor_alert", **alert, window_hours=snapshot["window_hours"])
    return snapshot, (2 if fail_on_alert and snapshot["alerts"] else 0)


async def worker_main() -> None:
    """Continuous monitoring loop; compose forwards alert logs to its collector."""
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
