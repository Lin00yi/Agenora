"""Regression coverage for public route-trace semantics."""
from __future__ import annotations

from src.harness.orchestration.intent import IntentAssessment
from src.harness.orchestration.planner import _plan_from_intent
from src.harness.orchestration.registry import build_default_agent_registry


def _knowledge_assessment() -> IntentAssessment:
    return IntentAssessment(
        domain="knowledge",
        intent="knowledge_lookup",
        risk="read",
        confidence="high",
        source="triage",
        rationale="needs_kb_fact",
    )


def test_unbound_knowledge_hypothesis_describes_chat_fallback_not_kb_retrieval() -> None:
    decision = _plan_from_intent(
        _knowledge_assessment(),
        has_kb=False,
        has_routable_kbs=False,
        registry=build_default_agent_registry(),
    )

    assert decision["tasks"][0]["type"] == "qa_chat"
    assert decision["reason"] == "general_chat"
    # The classifier rationale remains available to operators, but is not
    # presented as a statement about the executed plan.
    assert decision["intent"]["rationale"] == "needs_kb_fact"


def test_kb_selection_plan_describes_selection_not_completed_retrieval() -> None:
    decision = _plan_from_intent(
        _knowledge_assessment(),
        has_kb=False,
        has_routable_kbs=True,
        registry=build_default_agent_registry(),
    )

    assert decision["tasks"][0]["type"] == "kb_route"
    assert decision["reason"] == "checking_kb_relevance"
