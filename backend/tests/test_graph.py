"""Graph wiring test — verifies the default agent graph compiles."""
from src.agent.graph import build_graph


def test_graph_compiles():
    graph, _ = build_graph()
    assert graph is not None
    assert hasattr(graph, "ainvoke")
