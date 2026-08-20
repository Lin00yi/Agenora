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

    def trace_metadata(self) -> dict[str, Any]:
        """Safe, user-facing metadata for the execution timeline.

        Subclasses can expose a reviewed display label without leaking their
        schema, credentials, raw result, or internal implementation details.
        The empty default keeps built-in tools backward-compatible.
        """
        return {}


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
        from src.platform.observability import get_current_trace

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
                metadata = {"latency_ms": result.latency_ms}
                # Persist normalized retrieval outcome fields on the existing
                # tool span.  RAG monitoring reads only these numbers, never
                # prompts or chunk text, and supports historical traces that
                # do not yet carry the optional block.
                if name in {"search_kb", "search_kg"}:
                    raw = result.raw if isinstance(result.raw, dict) else {}
                    rows = raw.get("results") if isinstance(raw.get("results"), list) else []
                    max_score = raw.get("max_score")
                    if max_score is None:
                        scores = [item.get("score") for item in rows if isinstance(item, dict)]
                        numeric = []
                        for score in scores:
                            try:
                                numeric.append(float(score))
                            except (TypeError, ValueError):
                                continue
                        max_score = max(numeric) if numeric else None
                    metadata["rag"] = {
                        "source": "kb" if name == "search_kb" else "kg",
                        "result_count": raw.get("hits", len(rows)),
                        "candidate_count": raw.get("candidate_hits"),
                        "max_score": max_score,
                        "truncated": bool(raw.get("truncated", False)),
                    }
                    kb_id = raw.get("kb_id")
                    if kb_id:
                        metadata["rag"]["kb_id"] = str(kb_id)
                span.end(
                    status="error" if result.error else "ok",
                    error=result.error,
                    output=result.text if not result.error else None,
                    metadata=metadata,
                )
            return result
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - start) * 1000)
            if span is not None:
                span.end(status="error", error=str(exc), metadata={"latency_ms": latency_ms})
            return ToolResult(text="", latency_ms=latency_ms, error=str(exc))
        finally:
            if span is not None and span._span_token is not None:
                from src.platform.observability.tracer import _current_span_id

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

    Two cases:
      1. kb=None — general chat mode. Current time + web search tools so the LLM
         can answer date/time deterministically and pull real-time facts.
      2. kb=<user KB> — KB-bound mode: `search_kb`, plus optionally a tighter
         `web_search` fallback (v2-M6, gated by `user_kb_web_search_enabled`).

    `embedding_cfg` (v2-M1): per-user embedding override, threaded through to
    `KBSearchTool` so query embedding uses the user's chosen provider. None =
    fall back to env config.

    `reranker_cfg` (v3-M4): per-user cross-encoder reranker override, threaded
    through to `KBSearchTool` for second-stage rerank of search hits. None =
    skip rerank (default). System KBs ignore this regardless.

    `user_kb_web_search_enabled` (v2-M6): per-user opt-in flag. When True and
    a user KB is selected, also mount `WebSearchTool(default=3, cap=3)` —
    tighter than the unbound-chat mount because KB chunks should remain the
    primary source.
    """
    from src.harness.context.rag.policy import resolve_web_search_policy

    reg = ToolRegistry()

    # General chat mode. Keep the toolset minimal so the agent doesn't drift
    # toward KB tools when no KB is selected.
    if kb is None:
        from src.harness.tools.current_time import CurrentTimeTool
        from src.harness.tools.web_search import WebSearchTool

        web_policy = resolve_web_search_policy("general")
        reg.register(CurrentTimeTool())
        reg.register(
            WebSearchTool(
                max_results_default=web_policy.results_per_call,
                max_results_cap=web_policy.results_per_call,
            )
        )
        return reg

    # User-created KB — search_kb plus optional tighter web_search fallback.
    from src.harness.tools.kb_search import KBSearchTool
    from src.harness.tools.skill_report import make_kb_report_tool

    reg.register(KBSearchTool(kb=kb, embedding_cfg=embedding_cfg, reranker_cfg=reranker_cfg))
    if bool(getattr(kb, "kg_enabled", False)):
        from src.settings import get_settings
        from src.harness.tools.kg_search import KGSearchTool

        _lr = get_settings()
        if _lr.lightrag_enabled and (_lr.lightrag_base_url or "").strip():
            reg.register(KGSearchTool(kb_id=kb.id, kb_name=kb.name or ""))
    reg.register(make_kb_report_tool(llm_cfg=llm_cfg))
    if user_kb_web_search_enabled:
        from src.harness.tools.web_search import WebSearchTool

        # Tighter caps than general chat: KB is the primary source so web is
        # just a fallback for queries the KB doesn't cover.
        web_policy = resolve_web_search_policy("kb")
        reg.register(
            WebSearchTool(
                max_results_default=web_policy.results_per_call,
                max_results_cap=web_policy.results_per_call,
            )
        )
    return reg
