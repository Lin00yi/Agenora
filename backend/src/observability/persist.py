"""Persist finished TraceHandle trees into the app DB."""
from __future__ import annotations

import json

from src.storage.database import get_session_factory
from src.observability.models import Observation, Trace
from src.observability.tracer import TraceHandle, dump_trace_metadata


async def persist_trace(handle: TraceHandle) -> None:
    factory = get_session_factory()
    async with factory() as session:
        row = Trace(
            id=handle.id,
            conversation_id=handle.conversation_id,
            user_id=handle.user_id,
            name=handle.name,
            started_at=handle.started_at,
            ended_at=handle.ended_at,
            duration_ms=handle.duration_ms,
            status=handle.status,
            input_preview=handle.input_preview,
            output_preview=handle.output_preview,
            total_cost_usd=handle.total_cost_usd,
            metadata_json=dump_trace_metadata(handle.metadata),
        )
        session.add(row)
        for obs in handle.observations:
            session.add(
                Observation(
                    id=obs.id,
                    trace_id=handle.id,
                    parent_observation_id=obs.parent_observation_id,
                    type=obs.type,
                    name=obs.name,
                    started_at=obs.started_at,
                    ended_at=obs.ended_at,
                    duration_ms=obs.duration_ms,
                    status=obs.status,
                    error=obs.error,
                    model=obs.model,
                    usage_json=(
                        json.dumps(obs.usage, ensure_ascii=False) if obs.usage else None
                    ),
                    cost_usd=obs.cost_usd,
                    input_preview=obs.input_preview,
                    output_preview=obs.output_preview,
                    metadata_json=dump_trace_metadata(obs.metadata),
                )
            )
        await session.commit()
