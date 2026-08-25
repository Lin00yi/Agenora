"""web_search general-purpose web search tool."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from src.settings import get_settings
from src.harness.tools.base import Tool, ToolResult
from src.harness.tools.search_providers import get_search_provider
from src.capabilities.settings.domain.models import UserWebSearchConfig


_GENERIC_TITLES = {"untitled", "undefined", "null", "n/a"}
_ASCII_TERM_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{1,}", re.I)
_CJK_CHAR_RE = re.compile(r"[\u3400-\u9fff]")


def _normalized_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def _quality_score(query: str, *, title: str, url: str, body: str) -> int | None:
    """Return a lightweight relevance score or ``None`` for unusable results.

    Search providers already rank candidates. This guard removes common noisy
    rows (blank/Untitled cards, malformed URLs, and zero overlap with the
    query) before results become model evidence or visible citations.
    """
    clean_title = (title or "").strip()
    clean_body = (body or "").strip()
    parsed = urlparse((url or "").strip())
    if (
        not clean_title
        or clean_title.lower() in _GENERIC_TITLES
        or not clean_body
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
    ):
        return None

    haystack = _normalized_text(f"{clean_title} {clean_body} {parsed.netloc}")
    ascii_terms = set(_ASCII_TERM_RE.findall(_normalized_text(query)))
    ascii_hits = sum(term in haystack for term in ascii_terms)
    cjk_chars = set(_CJK_CHAR_RE.findall(query))
    cjk_hits = sum(char in haystack for char in cjk_chars)
    if ascii_terms and ascii_hits == 0 and cjk_hits < 2:
        return None
    if cjk_chars and cjk_hits < min(2, len(cjk_chars)) and ascii_hits == 0:
        return None
    return ascii_hits * 4 + cjk_hits


def _format_web_results(raw: dict[str, Any]) -> str:
    query = str(raw.get("query") or "")
    rows = raw.get("results") if isinstance(raw.get("results"), list) else []
    if not rows:
        return f"未找到关于 '{query}' 的高质量网络结果。"
    lines = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"[{index}] {str(row.get('title') or '').strip()}\n"
            f"    URL: {str(row.get('url') or '').strip()}\n"
            f"    摘要: {str(row.get('body') or '').strip()}"
        )
    return "\n\n".join(lines) or f"未找到关于 '{query}' 的高质量网络结果。"


def select_web_result_raw(raw: Any, *, indices: set[int]) -> dict[str, Any]:
    """Keep selected row indexes from a successful web-search payload."""
    payload = dict(raw) if isinstance(raw, dict) else {"results": []}
    rows = payload.get("results") if isinstance(payload.get("results"), list) else []
    kept = [dict(row) for index, row in enumerate(rows) if index in indices and isinstance(row, dict)]
    payload["results"] = kept
    payload["count"] = len(kept)
    payload["truncated"] = len(kept) < len(rows)
    return payload


class WebSearchTool(Tool):
    name = "web_search"

    def __init__(
        self,
        *,
        max_results_default: int = 5,
        max_results_cap: int = 5,
        search_config: UserWebSearchConfig | None = None,
    ) -> None:
        """Per-mount config.

        - max_results_default: used when the LLM omits max_results.
        - max_results_cap: hard upper bound advertised in schema and enforced
          again at execution time.
        """
        self._default = max(1, int(max_results_default))
        self._cap = max(self._default, int(max_results_cap))
        self._search_config = search_config
        self._provider_name = (
            search_config.provider if search_config else get_settings().web_search_provider or "duckduckgo"
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
            provider = get_search_provider(self._search_config)
            results = await provider.search(query, max_results=n)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(text="", latency_ms=0, error=f"web_search failed: {exc}")

        ranked: list[tuple[int, int, dict[str, str]]] = []
        for index, result in enumerate(results):
            title = result.title.strip()[:120]
            url = result.url.strip()
            body = result.body.strip()[:240]
            quality = _quality_score(query, title=title, url=url, body=body)
            if quality is not None:
                ranked.append(
                    (quality, -index, {"title": title, "url": url, "body": body, "_quality": quality})
                )
        ranked.sort(reverse=True)
        structured = [row for _, _, row in ranked[:n]]

        if not structured:
            return ToolResult(
                text=f"未找到关于 '{query}' 的高质量网络结果。",
                latency_ms=0,
                raw={
                    "count": 0,
                    "query": query,
                    "provider": self._provider_name,
                    "results": [],
                },
            )

        raw = {
            "count": len(structured),
            "query": query,
            "provider": provider.name,
            "results": structured,
        }
        return ToolResult(
            text=_format_web_results(raw),
            latency_ms=0,
            raw=raw,
        )
