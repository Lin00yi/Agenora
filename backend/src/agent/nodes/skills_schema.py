"""Skill tool schemas and legacy plan_node alias."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.state import AgentState
from src.infra.llm import CostTracker
from src.tools.base import ToolRegistry

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig


async def plan_node(
    state: AgentState,
    *,
    registry: ToolRegistry,
    cost: CostTracker,
    system_prompt: str = SYSTEM_PROMPT,
    include_travel_skill: bool = True,
    include_kb_skill: bool = False,
    llm_cfg: "UserLLMConfig | None" = None,
) -> AgentState:
    """Backward-compatible alias for the legacy graph/tests."""
    from .reason import reason_node

    return await reason_node(
        state,
        registry=registry,
        cost=cost,
        system_prompt=system_prompt,
        include_travel_skill=include_travel_skill,
        include_kb_skill=include_kb_skill,
        llm_cfg=llm_cfg,
    )


def _skill_tool_schema() -> dict[str, Any]:
    return {
        "name": "generate_travel_report",
        "description": (
            "调用 travel_report skill 生成结构化 Markdown 旅行报告。"
            "数据齐全后调用此工具，传入收集到的所有信息。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "date": {"type": "string"},
                "weather": {"type": "string"},
                "restaurants": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "餐厅列表，每项含 name/addr/signature_dishes/why_recommended",
                },
                "user_intent": {"type": "string", "description": "用户原始诉求摘要"},
            },
            "required": ["city", "date"],
        },
    }


def _kb_skill_tool_schema() -> dict[str, Any]:
    """v2-M8: generic report skill for user KBs.

    Mounted on KB-bound conversations (non-travel). The LLM should call this
    only when the user explicitly asks for a report / summary / structured
    document, not for every Q&A turn — KB chat default behavior is still
    direct prose answers grounded in search_kb chunks.
    """
    return {
        "name": "generate_kb_report",
        "description": (
            "把当前对话基于知识库 chunks（必要时含 web_search 结果）整理成一份"
            "结构化 Markdown 报告。**仅当用户明确要求**「生成报告」/「总结成文档」/"
            "「整理一份」时调用；普通问答**不要**调用本工具，直接基于 chunks 作答即可。"
            "调用前你必须已经通过 search_kb 拿到足够内容；citations 字段必须如实引用使用过的来源。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "报告标题（名词短语，概括主旨）",
                },
                "tldr": {
                    "type": "string",
                    "description": "一句话结论，≤80 中文字",
                },
                "sections": {
                    "type": "array",
                    "description": "正文段落列表，按逻辑顺序排",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "content": {
                                "type": "string",
                                "description": "完整段落 Markdown，可含列表 / 引用 / 加粗",
                            },
                        },
                        "required": ["heading", "content"],
                    },
                },
                "citations": {
                    "type": "array",
                    "description": "引用来源列表，按引用顺序排",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tag": {
                                "type": "string",
                                "enum": ["📚 KB", "🌐 Web"],
                                "description": "📚 KB = search_kb chunk，🌐 Web = web_search 结果",
                            },
                            "source": {
                                "type": "string",
                                "description": "KB chunk 的 filename，或 web 结果的 URL",
                            },
                            "score": {
                                "type": "number",
                                "description": "KB chunk 的相关度（0-1）；web 来源留空",
                            },
                        },
                        "required": ["tag", "source"],
                    },
                },
            },
            "required": ["title", "tldr", "sections", "citations"],
        },
    }
