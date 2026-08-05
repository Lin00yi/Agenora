"""web_search general-purpose web search tool."""
from __future__ import annotations

from typing import Any

from src.settings import get_settings
from src.tools.base import Tool, ToolResult
from src.tools.search_providers import get_search_provider


class WebSearchTool(Tool):
    name = "web_search"

    def __init__(
        self,
        *,
        max_results_default: int = 5,
        max_results_cap: int = 10,
    ) -> None:
        """Per-mount config.

        - max_results_default: used when the LLM omits max_results.
        - max_results_cap: hard upper bound advertised in schema and enforced
          again at execution time.
        """
        self._default = max(1, int(max_results_default))
        self._cap = max(self._default, int(max_results_cap))
        self._provider_name = (
            get_settings().web_search_provider or "duckduckgo"
        ).strip().lower()
        self.description = (
            "搜索互联网获取实时信息或模型预训练之外的事实。"
            "适合查询：最新新闻、近期数据、长尾事实、模型不掌握的内容。"
            f"当前搜索提供方：{self._provider_name}。"
            f"返回最大 {self._cap} 条结果（默认 {self._default}），每条含标题、URL、摘要。"
            "回答用户时可用正文点出关键链接；完整来源列表由界面结构化卡片展示，不必在文末重复罗列。"
        )
        self.input_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词。越具体越好；中英文都行。",
                },
                "max_results": {
                    "type": "integer",
                    "description": f"返回结果数 (1-{self._cap})，默认 {self._default}",
                    "default": self._default,
                    "minimum": 1,
                    "maximum": self._cap,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, max_results: int | None = None) -> ToolResult:
        if max_results is None:
            n = self._default
        else:
            try:
                n = max(1, min(int(max_results), self._cap))
            except (TypeError, ValueError):
                n = self._default

        try:
            provider = get_search_provider()
            results = await provider.search(query, max_results=n)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(text="", latency_ms=0, error=f"web_search failed: {exc}")

        if not results:
            return ToolResult(
                text=f"未找到关于 '{query}' 的网络结果。",
                latency_ms=0,
                raw={
                    "count": 0,
                    "query": query,
                    "provider": self._provider_name,
                    "results": [],
                },
            )

        lines: list[str] = []
        structured: list[dict[str, str]] = []
        for i, result in enumerate(results, 1):
            title = result.title.strip()[:120]
            url = result.url.strip()
            body = result.body.strip()[:240]
            lines.append(f"[{i}] {title}\n    URL: {url}\n    摘要: {body}")
            structured.append({"title": title, "url": url, "body": body})

        return ToolResult(
            text="\n\n".join(lines),
            latency_ms=0,
            raw={
                "count": len(results),
                "query": query,
                "provider": provider.name,
                "results": structured,
            },
        )
