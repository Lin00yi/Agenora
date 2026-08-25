"""TTFT projection coverage for admin trace observations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.platform.observability.models import Observation


def test_generation_serializes_ttft_from_completion_start_time() -> None:
    started_at = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
    observation = Observation(
        id="obs-1",
        trace_id="trace-1",
        type="generation",
        name="llm.chat_with_tools",
        started_at=started_at,
        metadata_json=(
            '{"completion_start_time":"'
            + (started_at + timedelta(milliseconds=321)).isoformat()
            + '"}'
        ),
    )

    assert observation.to_dict()["ttft_ms"] == 321


def test_non_generation_and_legacy_observations_do_not_invent_ttft() -> None:
    started_at = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
    observation = Observation(
        id="obs-1",
        trace_id="trace-1",
        type="span",
        name="reason",
        started_at=started_at,
        metadata_json='{"completion_start_time":"2026-08-25T08:00:00+00:00"}',
    )

    assert observation.to_dict()["ttft_ms"] is None
