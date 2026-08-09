"""ToolRegistry — async tool abstraction with Anthropic-compatible schema."""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict


class JsonSchema(TypedDict, total=False):
    type: str
    properties: dict[str, Any]
    required: list[str]


class ToolSchema(TypedDict):
    name: str
    description: str
    input_schema: JsonSchema | dict[str, Any]


class ToolRuntimeOptions(TypedDict, total=False):
    final_result: bool
    skill_name: str
    metadata: NotRequired[dict[str, Any]]


@dataclass
class ToolResult:
    text: str
    latency_ms: int
    raw: Any = None
    error: str | None = None


class Tool(abc.ABC):
    name: str
    description: str
    input_schema: dict[str, Any]

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...

    def to_schema(self) -> ToolSchema:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_anthropic(self) -> ToolSchema:
        """Backward-compatible alias for the canonical internal schema."""
        return self.to_schema()


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_schemas(self) -> list[ToolSchema]:
        return [t.to_schema() for t in self._tools.values()]

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        from src.observability import get_current_trace

        tool = self.get(name)
        if tool is None:
            return ToolResult(text="", latency_ms=0, error=f"Unknown tool: {name}")

        trace = get_current_trace()
        span = (
            trace.tool(name, input=args, metadata={"tool": name})
            if trace is not None
            else None
        )
        if span is not None:
            span.__enter__()
        start = time.perf_counter()
        try:
            result = await tool.execute(**args)
            if result.latency_ms == 0:
                result.latency_ms = int((time.perf_counter() - start) * 1000)
            if span is not None:
                span.end(
                    status="error" if result.error else "ok",
                    error=result.error,
                    output=result.text if not result.error else None,
                    metadata={"latency_ms": result.latency_ms},
                )
            return result
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - start) * 1000)
            if span is not None:
                span.end(status="error", error=str(exc), metadata={"latency_ms": latency_ms})
            return ToolResult(text="", latency_ms=latency_ms, error=str(exc))
        finally:
            if span is not None and span._span_token is not None:
                from src.observability.tracer import _current_span_id

                _current_span_id.reset(span._span_token)
                span._span_token = None



def build_default_registry(
    kb=None,
    embedding_cfg=None,
    *,
    reranker_cfg=None,
    llm_cfg=None,
    user_kb_web_search_enabled: bool = False,
) -> ToolRegistry:
    """Build the agent's tool set based on which KB (if any) is active.

    Three cases (v2-M4):
      1. kb=None — general chat mode. Current time + web search tools so the LLM
         can answer date/time deterministically and pull real-time facts.
      2. kb=<system travel demo KB> — travel four-tool kit (weather + restaurant_kb
         + amap + the `generate_travel_report` skill that's wired in `graph.py`).
         Travel behavior is reachable only via this explicit selection.
      3. kb=<user KB> — KB-bound mode: `search_kb`, plus optionally a tighter
         `web_search` fallback (v2-M6, gated by `user_kb_web_search_enabled`).

    `embedding_cfg` (v2-M1): per-user embedding override, threaded through to
    `KBSearchTool` so query embedding uses the user's chosen provider. None =
    fall back to env config.

    `reranker_cfg` (v3-M4): per-user cross-encoder reranker override, threaded
    through to `KBSearchTool` for second-stage rerank of search hits. None =
    skip rerank (default). System KBs ignore this regardless.

    `user_kb_web_search_enabled` (v2-M6): per-user opt-in flag. When True and
    a user KB is selected, also mount `WebSearchTool(default=3, cap=5)` —
    tighter than the unbound-chat mount because KB chunks should remain the
    primary source.
    """
    from src.kb.models import SYSTEM_TRAVEL_KB_ID

    reg = ToolRegistry()

    # General chat mode. Keep the toolset minimal so the agent doesn't drift
    # toward travel / KB tools when no KB is selected.
    if kb is None:
        from src.tools.current_time import CurrentTimeTool
        from src.tools.web_search import WebSearchTool

        reg.register(CurrentTimeTool())
        reg.register(WebSearchTool())
        return reg

    # Built-in travel demo KB — keep v1 four-tool kit.
    if kb.id == SYSTEM_TRAVEL_KB_ID:
        from src.tools.amap_fallback import AmapFallbackTool
        from src.tools.restaurant_rag import RestaurantRagTool
        from src.tools.skill_report import make_travel_report_tool
        from src.tools.weather import WeatherTool

        reg.register(WeatherTool())
        reg.register(RestaurantRagTool())
        reg.register(AmapFallbackTool())
        reg.register(make_travel_report_tool(llm_cfg=llm_cfg))
        return reg

    # User-created KB — search_kb plus optional tighter web_search fallback.
    from src.tools.kb_search import KBSearchTool
    from src.tools.skill_report import make_kb_report_tool

    reg.register(KBSearchTool(kb=kb, embedding_cfg=embedding_cfg, reranker_cfg=reranker_cfg))
    if bool(getattr(kb, "kg_enabled", False)):
        from src.settings import get_settings
        from src.tools.kg_search import KGSearchTool

        _lr = get_settings()
        if _lr.lightrag_enabled and (_lr.lightrag_base_url or "").strip():
            reg.register(KGSearchTool(kb_id=kb.id, kb_name=kb.name or ""))
    reg.register(make_kb_report_tool(llm_cfg=llm_cfg))
    if user_kb_web_search_enabled:
        from src.tools.web_search import WebSearchTool

        # Tighter caps than general chat: KB is the primary source so web is
        # just a fallback for queries the KB doesn't cover.
        reg.register(WebSearchTool(max_results_default=3, max_results_cap=5))
    return reg
