from types import SimpleNamespace

import pytest

from src.harness.agents.react import build_react_graph
from src.platform.observability.catalog import TRACE_SCHEMA_VERSION, observation_lifecycle


def test_trace_node_lifecycle_preserves_historical_semantics() -> None:
    assert TRACE_SCHEMA_VERSION == 2
    assert observation_lifecycle("scope") == "active"
    assert observation_lifecycle("supervisor_dispatch") == "legacy"
    assert observation_lifecycle("supervisor.route.triage") == "legacy"
    assert observation_lifecycle("get_weather") == "retired"
    assert observation_lifecycle("unregistered_plugin_tool") == "unknown"


@pytest.mark.asyncio
async def test_react_scope_is_a_first_class_trace_observation(monkeypatch) -> None:
    """The visible Trace must include every node in the default ReAct graph."""
    import src.platform.observability.tracer as tracer

    # Exercise the in-memory trace only; this test must not write the app DB.
    monkeypatch.setattr(tracer, "tracing_active", lambda: True)
    monkeypatch.setattr(
        tracer,
        "get_settings",
        lambda: SimpleNamespace(trace_enabled=False, trace_store_io=False),
    )
    monkeypatch.setattr(tracer, "get_langfuse", lambda: None)

    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    trace = tracer.start_trace("test")
    assert trace is not None
    graph, _ = build_react_graph(emit=emit)
    scope = graph.get_graph().nodes["scope"].data

    result = await scope.afunc({"messages": []})

    assert result["runtime_scope"]["kind"] == "general"
    assert [(obs.name, obs.metadata["kind"]) for obs in trace.observations] == [
        ("scope", "general")
    ]
    assert events == [
        {
            "event": "agent_route",
            "agent": "react",
            "scope": "general",
            "source": "none",
            "confidence": "high",
            "reason": "no_kb_candidates",
        }
    ]
    await trace.finish()
