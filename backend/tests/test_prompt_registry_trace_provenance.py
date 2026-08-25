"""Published Prompt Registry provenance survives the ReAct state contract."""
from __future__ import annotations

import pytest

from src.harness.agents.react import graph as react_graph
from src.harness.orchestration.intent import IntentAssessment
from src.harness.prompts.registry import PromptResolution
from src.harness.prompts.system import PROMPT_KEY_GENERAL
from src.harness.runtime.scope import RuntimeScope


@pytest.mark.asyncio
async def test_react_state_keeps_answer_and_scope_prompt_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer_prompt = PromptResolution(
        content="answer policy",
        key=PROMPT_KEY_GENERAL,
        version=9,
        digest="answer-digest",
        source="registry",
    )
    scope_metadata = {
        "key": "runtime_scope_classification",
        "version": 4,
        "digest": "scope-digest",
        "source": "registry",
    }

    async def fake_scope(**_kwargs: object) -> RuntimeScope:
        return RuntimeScope(
            kind="general",
            intent=IntentAssessment(
                domain="general",
                intent="general_chat",
                risk="none",
                confidence="high",
                source="triage",
            ),
            intent_prompt_registry=scope_metadata,
        )

    async def fake_reason(state: dict, **_kwargs: object) -> dict:
        return {
            **state,
            "final_report": "done",
            "pending_tool_calls": [],
            "iterations": 1,
            "cost_usd": 0.0,
        }

    monkeypatch.setattr(react_graph, "resolve_runtime_scope", fake_scope)
    monkeypatch.setattr(react_graph, "reason_node", fake_reason)

    graph, _ = react_graph.build_react_graph(
        prompt_overrides={PROMPT_KEY_GENERAL: answer_prompt},
    )
    result = await graph.ainvoke({"messages": [{"role": "user", "content": "hello"}]})

    assert result["prompt_registry"] == answer_prompt.trace_metadata()
    assert result["kb_auto_route"]["intent_prompt_registry"] == scope_metadata
