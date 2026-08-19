"""Wrap report skills as first-class tools."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.skills.loader import invoke_skill
from src.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig

ArgsTransform = Callable[[dict[str, Any]], dict[str, Any]]


class SkillTool(Tool):
    """A Tool adapter for SKILL.md-backed report generators."""

    def __init__(
        self,
        *,
        name: str,
        skill_name: str,
        description: str,
        input_schema: dict[str, Any],
        llm_cfg: "UserLLMConfig | None" = None,
        argument_transform: ArgsTransform | None = None,
        final_result: bool = True,
    ) -> None:
        self.name = name
        self.skill_name = skill_name
        self.description = description
        self.input_schema = input_schema
        self.llm_cfg = llm_cfg
        self.argument_transform = argument_transform
        self.final_result = final_result

    async def execute(self, **kwargs: Any) -> ToolResult:
        args = dict(kwargs)
        if self.argument_transform is not None:
            args = self.argument_transform(args)
        text = await invoke_skill(self.skill_name, args, llm_cfg=self.llm_cfg)
        return ToolResult(
            text=text,
            latency_ms=0,
            raw={"skill_name": self.skill_name, "final_result": self.final_result},
        )


def make_kb_report_tool(*, llm_cfg: "UserLLMConfig | None" = None) -> SkillTool:
    return SkillTool(
        name="generate_kb_report",
        skill_name="general_report",
        llm_cfg=llm_cfg,
        description=(
            "把当前对话基于知识库 chunks（必要时含 web_search 结果）整理成一份"
            "结构化 Markdown 报告。仅当用户明确要求“生成报告”“总结成文档”"
            "“整理一份”时调用；普通问答不要调用本工具。调用前必须已经通过"
            " search_kb 拿到足够内容，citations 字段必须如实引用使用过的来源。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "报告标题（名词短语，概括主旨）",
                },
                "tldr": {
                    "type": "string",
                    "description": "一句话结论（不超过 80 个中文字符）",
                },
                "sections": {
                    "type": "array",
                    "description": "正文段落列表，按逻辑顺序排列",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "content": {
                                "type": "string",
                                "description": (
                                    "完整段落 Markdown，可含列表、引用、加粗"
                                ),
                            },
                        },
                        "required": ["heading", "content"],
                    },
                },
                "citations": {
                    "type": "array",
                    "description": "引用来源列表，按引用顺序排列",
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
    )
