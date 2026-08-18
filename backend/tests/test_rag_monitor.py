from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_rag_monitor_aggregates_trace_metadata_and_raises_threshold_alerts(db):
    from src.infra.database import get_session_factory
    from src.observability.models import Observation, Trace
    from src.observability.rag_metrics import build_rag_monitor_snapshot
    from src.settings import Settings

    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        trace_ids = [uuid.uuid4().hex for _ in range(3)]
        session.add_all([Trace(id=trace_id, name="chat", started_at=now) for trace_id in trace_ids])
        session.add_all(
            [
                Observation(
                    id=uuid.uuid4().hex,
                    trace_id=trace_ids[0],
                    name="search_kb",
                    type="tool",
                    started_at=now,
                    duration_ms=120,
                    status="ok",
                    metadata_json=json.dumps({"rag": {"result_count": 0, "max_score": 0.20}}),
                ),
                Observation(
                    id=uuid.uuid4().hex,
                    trace_id=trace_ids[1],
                    name="search_kb",
                    type="tool",
                    started_at=now,
                    duration_ms=900,
                    status="error",
                    metadata_json=json.dumps({"rag": {"result_count": 2, "max_score": 0.30}}),
                ),
                Observation(
                    id=uuid.uuid4().hex,
                    trace_id=trace_ids[2],
                    name="search_kg",
                    type="tool",
                    started_at=now,
                    duration_ms=500,
                    status="ok",
                    metadata_json=json.dumps({"rag": {"result_count": 1}}),
                ),
            ]
        )
        await session.commit()

        snapshot = await build_rag_monitor_snapshot(
            session,
            settings=Settings(
                rag_monitor_min_calls=3,
                rag_monitor_max_error_rate=0.2,
                rag_monitor_max_empty_rate=0.2,
                rag_monitor_max_p95_latency_ms=800,
                rag_monitor_min_avg_top_score=0.5,
            ),
        )

    assert snapshot["sample_sufficient"] is True
    assert snapshot["metrics"]["retrieval_calls"] == 3
    assert snapshot["metrics"]["retrieval_traces"] == 3
    assert snapshot["metrics"]["empty_rate"] == pytest.approx(1 / 3)
    assert snapshot["metrics"]["error_rate"] == pytest.approx(1 / 3)
    assert snapshot["metrics"]["p95_latency_ms"] == 900
    assert snapshot["metrics"]["avg_top_score"] == pytest.approx(0.25)
    assert {alert["code"] for alert in snapshot["alerts"]} == {
        "rag_error_rate",
        "rag_empty_rate",
        "rag_p95_latency",
        "rag_low_top_score",
    }


@pytest.mark.asyncio
async def test_admin_rag_monitor_endpoint_requires_admin_and_returns_contract(client, create_user):
    from src.auth.tokens import issue_token

    user = await create_user("rag-monitor-admin@example.test", is_admin=True)
    response = await client.get(
        "/api/admin/rag/monitor?hours=2",
        headers={"Authorization": f"Bearer {issue_token(user.id, user.email)}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["window_hours"] == 2
    assert set(data["metrics"]) >= {
        "retrieval_calls",
        "empty_rate",
        "error_rate",
        "p95_latency_ms",
        "avg_top_score",
    }


@pytest.mark.asyncio
async def test_admin_rag_evaluation_endpoint_returns_metadata_only(
    client, create_user, create_kb, monkeypatch
):
    from src.auth.tokens import issue_token
    from src.tools.base import ToolResult
    from src.tools.kb_search import KBSearchTool

    admin = await create_user("rag-evaluation-admin@example.test", is_admin=True)
    kb = await create_kb(admin.id, name="Evaluation KB")

    async def fake_execute(self, query: str, limit: int = 3):  # noqa: ARG001
        return ToolResult(
            text="document body must stay private",
            latency_ms=1,
            raw={
                "results": [
                    {
                        "doc_id": "document-1",
                        "filename": "private-source.md",
                        "score": 0.91,
                        "text_preview": "private source text",
                    }
                ]
            },
        )

    monkeypatch.setattr(KBSearchTool, "execute", fake_execute)
    response = await client.post(
        "/api/admin/rag/evaluate-retrieval",
        headers={"Authorization": f"Bearer {issue_token(admin.id, admin.email)}"},
        json={"kb_id": kb.id, "cases": [{"id": "case-1", "query": "test query"}]},
    )

    assert response.status_code == 200
    prediction = response.json()["predictions"][0]
    assert prediction["retrieved"] == [
        {"document_id": "document-1", "filename": "private-source.md", "score": 0.91}
    ]
    assert "text_preview" not in str(response.json())
    assert "document body must stay private" not in str(response.json())


@pytest.mark.asyncio
async def test_real_kb_tool_span_emits_privacy_safe_rag_metrics(db, monkeypatch):
    from src.infra.database import get_session_factory
    from src.observability import start_trace
    from src.observability.models import Observation
    from src.observability.rag_metrics import build_rag_monitor_snapshot
    from src.settings import Settings, get_settings
    from src.tools.base import Tool, ToolRegistry, ToolResult

    monkeypatch.setenv("TRACE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    get_settings.cache_clear()

    class SyntheticKbTool(Tool):
        name = "search_kb"
        description = "test"
        input_schema = {"type": "object"}

        async def execute(self, **_kwargs):
            return ToolResult(
                text="private document text must not enter metrics",
                latency_ms=17,
                raw={
                    "hits": 1,
                    "candidate_hits": 4,
                    "max_score": 0.88,
                    "results": [{"doc_id": "private-doc", "score": 0.88}],
                },
            )

    trace = start_trace("chat", input="private user question")
    assert trace is not None
    registry = ToolRegistry()
    registry.register(SyntheticKbTool())
    await registry.call("search_kb", {"query": "private query"})
    await trace.finish(output="private answer")

    factory = get_session_factory()
    async with factory() as session:
        observation = (await session.execute(select(Observation))).scalar_one()
        assert observation.input_preview is not None  # normal Trace policy is unchanged
        rag = observation.metadata_dict()["rag"]
        assert rag == {
            "source": "kb",
            "result_count": 1,
            "candidate_count": 4,
            "max_score": 0.88,
            "truncated": False,
        }
        assert "private document text" not in json.dumps(rag)
        snapshot = await build_rag_monitor_snapshot(
            session, settings=Settings(rag_monitor_min_calls=1)
        )
    assert snapshot["metrics"]["avg_top_score"] == pytest.approx(0.88)
    assert snapshot["metrics"]["empty_rate"] == pytest.approx(0.0)
