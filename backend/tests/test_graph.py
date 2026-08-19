"""Graph wiring test — sub-agents and main supervisor compile."""
import pytest

from src.agent.graph import build_chat_graph, build_graph
from src.agent.main_agent import build_supervisor_graph
from src.agent.sub_agents.chat_agent import build_chat_graph as build_chat_direct
from src.agent.sub_agents.rag_agent import build_rag_graph


def test_graph_compiles():
    graph, _ = build_graph()
    assert graph is not None
    assert hasattr(graph, "ainvoke")


def test_chat_graph_compiles():
    graph, _ = build_chat_graph()
    assert hasattr(graph, "ainvoke")
    direct, _ = build_chat_direct()
    assert hasattr(direct, "ainvoke")


def test_rag_graph_requires_kb():
    with pytest.raises(ValueError, match="requires kb"):
        build_rag_graph(kb=None)


def test_supervisor_compiles():
    graph, _ = build_supervisor_graph()
    assert hasattr(graph, "ainvoke")
