"""Executable sub-agents and their shared ReAct loop."""

from src.agents.chat import build_chat_graph
from src.agents.rag import build_rag_graph
from src.tools.base import ToolRegistry

__all__ = ["build_chat_graph", "build_graph", "build_rag_graph"]


def build_graph(
    registry: ToolRegistry | None = None,
    emit=None,
    *,
    kb=None,
    llm_cfg=None,
    complex_llm_cfg=None,
    triage_llm_cfg=None,
    fallback_llm_cfg=None,
    embedding_cfg=None,
    reranker_cfg=None,
    kb_web_search_enabled: bool = False,
):
    """Direct subgraph helper — kb=None → chat, else → rag.

    Production chat uses ``src.runtime.build_supervisor_graph``.
    """
    if kb is None:
        return build_chat_graph(
            registry,
            emit,
            llm_cfg=llm_cfg,
            complex_llm_cfg=complex_llm_cfg,
            fallback_llm_cfg=fallback_llm_cfg,
        )
    return build_rag_graph(
        registry,
        emit,
        kb=kb,
        llm_cfg=llm_cfg,
        complex_llm_cfg=complex_llm_cfg,
        triage_llm_cfg=triage_llm_cfg,
        fallback_llm_cfg=fallback_llm_cfg,
        embedding_cfg=embedding_cfg,
        reranker_cfg=reranker_cfg,
        kb_web_search_enabled=kb_web_search_enabled,
    )
