"""Bounded data-lifecycle sweep for high-volume derived and operational data."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.capabilities.conversations.models import Conversation
from src.capabilities.knowledge.domain.models import Document, KbEvalRun
from src.capabilities.knowledge.application.evaluation import EVAL_OBJECT_PREFIX, EVAL_RUNS_BASE
from src.platform.files.object_storage import get_object_storage
from src.platform.observability.models import Trace
from src.platform.tasks.models import OperationJob
from src.settings import get_settings


@dataclass
class RetentionResult:
    traces_deleted: int = 0
    traces_archived: int = 0
    conversations_deleted: int = 0
    parsed_text_cleared: int = 0
    eval_runs_deleted: int = 0
    operation_jobs_deleted: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _cutoff(days: int, now: datetime) -> datetime | None:
    return now - timedelta(days=days) if days > 0 else None


async def run_retention_sweep(session: AsyncSession, *, limit: int = 200) -> RetentionResult:
    """Apply configured retention in small transactional batches.

    User conversations and parsed text default to disabled; enabling either is
    an explicit product-data policy. Trace archival is written before deleting
    the hot DB copy, and object-storage lifecycle rules should expire the
    ``trace-archive/`` prefix according to the deployment's compliance policy.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    result = RetentionResult()
    batch = max(1, min(int(limit), 1_000))

    trace_cutoff = _cutoff(int(settings.trace_retention_days), now)
    if trace_cutoff is not None:
        traces = list(
            (
                await session.execute(
                    select(Trace)
                    .options(selectinload(Trace.observations))
                    .where(Trace.started_at < trace_cutoff)
                    .order_by(Trace.started_at)
                    .limit(batch)
                )
            ).scalars()
        )
        for trace in traces:
            if settings.trace_archive_enabled:
                month = trace.started_at.astimezone(timezone.utc).strftime("%Y-%m")
                key = f"trace-archive/{month}/{trace.id}.json"
                payload = {
                    "trace": trace.to_summary_dict(),
                    "observations": [item.to_dict() for item in trace.observations],
                }
                await get_object_storage().put(
                    key,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                    content_type="application/json; charset=utf-8",
                )
                result.traces_archived += 1
            await session.delete(trace)
            result.traces_deleted += 1
        if traces:
            await session.commit()

    conversation_cutoff = _cutoff(int(settings.conversation_retention_days), now)
    if conversation_cutoff is not None:
        conversations = list(
            (
                await session.execute(
                    select(Conversation)
                    .where(Conversation.updated_at < conversation_cutoff)
                    .order_by(Conversation.updated_at)
                    .limit(batch)
                )
            ).scalars()
        )
        for conversation in conversations:
            await session.delete(conversation)
            result.conversations_deleted += 1
        if conversations:
            await session.commit()

    parsed_cutoff = _cutoff(int(settings.parsed_text_retention_days), now)
    if parsed_cutoff is not None:
        documents = list(
            (
                await session.execute(
                    select(Document)
                    .where(Document.updated_at < parsed_cutoff, Document.parsed_text != "")
                    .order_by(Document.updated_at)
                    .limit(batch)
                )
            ).scalars()
        )
        for document in documents:
            document.parsed_text = ""
            result.parsed_text_cleared += 1
        if documents:
            await session.commit()

    eval_cutoff = _cutoff(int(settings.eval_run_retention_days), now)
    if eval_cutoff is not None:
        old_runs = list(
            (
                await session.execute(
                    select(KbEvalRun)
                    .where(KbEvalRun.created_at < eval_cutoff)
                    .order_by(KbEvalRun.created_at)
                    .limit(batch)
                )
            ).scalars()
        )
        for run in old_runs:
            if run.retrieval_jsonl_path:
                try:
                    if run.retrieval_jsonl_path.startswith(f"{EVAL_OBJECT_PREFIX}/"):
                        await get_object_storage().delete(run.retrieval_jsonl_path)
                    else:
                        legacy = (EVAL_RUNS_BASE / run.retrieval_jsonl_path).resolve()
                        if legacy.is_relative_to(EVAL_RUNS_BASE.resolve()):
                            legacy.unlink(missing_ok=True)
                except FileNotFoundError:
                    pass
            await session.delete(run)
            result.eval_runs_deleted += 1
        if old_runs:
            await session.commit()

    job_cutoff = _cutoff(int(settings.operation_job_retention_days), now)
    if job_cutoff is not None:
        deleted = await session.execute(
            delete(OperationJob).where(
                OperationJob.status.in_(("done", "dead_letter")),
                OperationJob.completed_at.is_not(None),
                OperationJob.completed_at < job_cutoff,
            )
        )
        result.operation_jobs_deleted = int(deleted.rowcount or 0)
        if result.operation_jobs_deleted:
            await session.commit()
    return result
