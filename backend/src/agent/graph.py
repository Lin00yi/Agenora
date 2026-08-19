"""Compatibility facade for single-agent graph builders.

Prefer:
  ``from src.agent.sub_agents.chat_agent import build_chat_graph``
  ``from src.agent.sub_agents.rag_agent import build_rag_graph``
  ``from src.agent.main_agent import build_supervisor_graph``
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.sub_agents.chat_agent import build_chat_graph
from src.agent.sub_agents.rag_agent import build_rag_graph
from src.tools.base import ToolRegistry

if TYPE_CHECKING:
    from src.settings_user import UserEmbeddingConfig, UserLLMConfig, UserRerankerConfig


def build_graph(
    registry: ToolRegistry | None = None,
    emit=None,
    *,
    kb=None,
    llm_cfg: "UserLLMConfig | None" = None,
    complex_llm_cfg: "UserLLMConfig | None" = None,
    triage_llm_cfg: "UserLLMConfig | None" = None,
    fallback_llm_cfg: "UserLLMConfig | None" = None,
    embedding_cfg: "UserEmbeddingConfig | None" = None,
    reranker_cfg: "UserRerankerConfig | None" = None,
    kb_web_search_enabled: bool = False,
):
    """Legacy wrapper — kb=None → chat, else → rag."""
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


__all__ = ["build_chat_graph", "build_rag_graph", "build_graph"]
