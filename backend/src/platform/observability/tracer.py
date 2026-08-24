"""In-memory span tree + flush to DB and/or Langfuse."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterator, Literal

import structlog

from src.platform.observability.langfuse_client import (
    build_langfuse_tags,
    get_langfuse,
    resolve_langfuse_environment,
    stamp_langfuse_trace_attrs,
)
from src.platform.observability.preview import preview_text, usage_from_sdk
from src.settings import get_settings

log = structlog.get_logger()

ObservationType = Literal["span", "generation", "tool"]

_current_trace: ContextVar["TraceHandle | None"] = ContextVar("obs_trace", default=None)
_current_span_id: ContextVar[str | None] = ContextVar("obs_span_id", default=None)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


def tracing_active() -> bool:
    """True when either internal DB tracing or Langfuse export is on."""
    s = get_settings()
    if s.trace_enabled:
        return True
    return get_langfuse() is not None


@dataclass
class ObservationData:
    id: str
    parent_observation_id: str | None
    type: ObservationType
    name: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    status: str = "ok"
    error: str | None = None
    model: str | None = None
    usage: dict[str, int] | None = None
    cost_usd: float | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _t0: float = field(default_factory=time.perf_counter, repr=False)
    _lf_obs: Any = field(default=None, repr=False)


@dataclass
class TraceHandle:
    id: str
    name: str
    conversation_id: str | None
    user_id: str | None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    status: str = "ok"
    input_preview: str | None = None
    output_preview: str | None = None
    total_cost_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    observations: list[ObservationData] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter, repr=False)
    _lf_root: Any = field(default=None, repr=False)
    _lf_by_id: dict[str, Any] = field(default_factory=dict, repr=False)
    _lf_tags: list[str] = field(default_factory=list, repr=False)
    _token: Token | None = field(default=None, repr=False)
    _finished: bool = field(default=False, repr=False)

    def _stamp_lf(self, lf_obs: Any) -> None:
        stamp_langfuse_trace_attrs(
            lf_obs,
            trace_name=self.name,
            user_id=self.user_id,
            session_id=self.conversation_id,
            tags=self._lf_tags,
            metadata=self.metadata,
            environment=resolve_langfuse_environment(),
        )

    def start_observation(
        self,
        name: str,
        *,
        as_type: ObservationType = "span",
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        parent_id: str | None = None,
    ) -> "SpanHandle":
        s = get_settings()
        parent = parent_id if parent_id is not None else _current_span_id.get()
        obs = ObservationData(
            id=_new_id(),
            parent_observation_id=parent,
            type=as_type,
            name=name,
            started_at=_utcnow(),
            model=model,
            input_preview=preview_text(input, store_io=s.trace_store_io),
            metadata=dict(metadata or {}),
        )
        self.observations.append(obs)

        lf_parent = self._lf_by_id.get(parent) if parent else self._lf_root
        if lf_parent is not None:
            try:
                lf_obs = lf_parent.start_observation(
                    name=name,
                    as_type=as_type,
                    input=input if s.trace_store_io else None,
                    metadata=metadata or {},
                    model=model,
                )
                self._stamp_lf(lf_obs)
                obs._lf_obs = lf_obs
                self._lf_by_id[obs.id] = lf_obs
            except Exception as exc:  # noqa: BLE001
                log.warning("langfuse_span_start_failed", error=str(exc), name=name)

        return SpanHandle(trace=self, observation=obs)

    def span(self, name: str, **kwargs: Any) -> "SpanHandle":
        return self.start_observation(name, as_type="span", **kwargs)

    def generation(self, name: str, **kwargs: Any) -> "SpanHandle":
        return self.start_observation(name, as_type="generation", **kwargs)

    def tool(self, name: str, **kwargs: Any) -> "SpanHandle":
        return self.start_observation(name, as_type="tool", **kwargs)

    async def finish(
        self,
        *,
        status: str = "ok",
        output: Any = None,
        error: str | None = None,
        total_cost_usd: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        s = get_settings()
        self.ended_at = _utcnow()
        self.duration_ms = int((time.perf_counter() - self._t0) * 1000)
        self.status = "error" if error else status
        if error:
            self.metadata["error"] = error
        if metadata:
            self.metadata.update(metadata)
        if total_cost_usd is not None:
            self.total_cost_usd = total_cost_usd
        self.output_preview = preview_text(output, store_io=s.trace_store_io)

        # Close any still-open observations (best-effort).
        for obs in self.observations:
            if obs.ended_at is None:
                obs.ended_at = self.ended_at
                obs.duration_ms = int((time.perf_counter() - obs._t0) * 1000)
                if self.status == "error" and obs.status == "ok":
                    obs.status = "error"
                self._end_lf(obs)

        # Persist internal DB first. Langfuse flush is sync/network-bound and
        # must not block or cancel-away the local sink when SSE clients disconnect.
        if s.trace_enabled:
            try:
                from src.platform.observability.persist import persist_trace

                await persist_trace(self)
            except Exception as exc:  # noqa: BLE001
                log.warning("trace_persist_failed", error=str(exc), trace_id=self.id)

        if self._lf_root is not None:
            try:
                self._stamp_lf(self._lf_root)
                self._lf_root.update(
                    output=output if s.trace_store_io else None,
                    metadata={**self.metadata, "status": self.status},
                )
                if total_cost_usd is not None:
                    try:
                        self._lf_root.update(cost_details={"total": total_cost_usd})
                    except Exception:  # noqa: BLE001
                        pass
                # Legacy trace-level I/O (still used by some Langfuse evaluators).
                try:
                    if hasattr(self._lf_root, "set_trace_io"):
                        self._lf_root.set_trace_io(
                            input=self.input_preview if s.trace_store_io else None,
                            output=output if s.trace_store_io else None,
                        )
                except Exception:  # noqa: BLE001
                    pass
                self._lf_root.end()
                lf = get_langfuse()
                if lf is not None and hasattr(lf, "flush"):
                    await asyncio.to_thread(lf.flush)
            except Exception as exc:  # noqa: BLE001
                log.warning("langfuse_trace_end_failed", error=str(exc))

        # Token.reset only works in the Context that called set(). Chat may
        # start the trace in the request task and finish inside create_task.
        try:
            if self._token is not None:
                _current_trace.reset(self._token)
        except ValueError:
            _current_trace.set(None)
        self._token = None
        _current_span_id.set(None)

    def _end_lf(self, obs: ObservationData) -> None:
        if obs._lf_obs is None:
            return
        s = get_settings()
        try:
            update_kwargs: dict[str, Any] = {
                "metadata": {**obs.metadata, "status": obs.status},
            }
            if obs.output_preview is not None and s.trace_store_io:
                update_kwargs["output"] = obs.output_preview
            if obs.error:
                update_kwargs["level"] = "ERROR"
                update_kwargs["status_message"] = obs.error
            if obs.model:
                update_kwargs["model"] = obs.model
            if obs.usage:
                update_kwargs["usage_details"] = obs.usage
            if obs.cost_usd is not None:
                update_kwargs["cost_details"] = {"total": obs.cost_usd}
            obs._lf_obs.update(**update_kwargs)
            obs._lf_obs.end()
        except Exception as exc:  # noqa: BLE001
            log.warning("langfuse_span_end_failed", error=str(exc), name=obs.name)


@dataclass
class SpanHandle:
    trace: TraceHandle
    observation: ObservationData
    _span_token: Token | None = field(default=None, repr=False)
    _ended: bool = field(default=False, repr=False)

    def __enter__(self) -> "SpanHandle":
        self._span_token = _current_span_id.set(self.observation.id)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if exc is not None:
            self.end(status="error", error=str(exc))
        else:
            self.end()
        if self._span_token is not None:
            _current_span_id.reset(self._span_token)
            self._span_token = None

    async def __aenter__(self) -> "SpanHandle":
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.__exit__(exc_type, exc, tb)

    def update(
        self,
        *,
        output: Any = None,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        usage: Any = None,
        cost_usd: float | None = None,
        status: str | None = None,
        error: str | None = None,
        completion_start_time: Any = None,
    ) -> None:
        s = get_settings()
        obs = self.observation
        if output is not None:
            obs.output_preview = preview_text(output, store_io=s.trace_store_io)
        if input is not None:
            obs.input_preview = preview_text(input, store_io=s.trace_store_io)
        if metadata:
            obs.metadata.update(metadata)
        if model is not None:
            obs.model = model
        if usage is not None:
            obs.usage = usage if isinstance(usage, dict) else usage_from_sdk(usage)
        if cost_usd is not None:
            obs.cost_usd = cost_usd
        if status is not None:
            obs.status = status
        if error is not None:
            obs.error = error
            obs.status = "error"
        if completion_start_time is not None:
            obs.metadata["completion_start_time"] = (
                completion_start_time.isoformat()
                if hasattr(completion_start_time, "isoformat")
                else str(completion_start_time)
            )
            if obs._lf_obs is not None:
                try:
                    obs._lf_obs.update(completion_start_time=completion_start_time)
                except Exception:  # noqa: BLE001
                    pass

    def end(
        self,
        *,
        status: str | None = None,
        error: str | None = None,
        output: Any = None,
        usage: Any = None,
        cost_usd: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._ended:
            return
        self._ended = True
        if output is not None or usage is not None or cost_usd is not None or metadata or status or error:
            self.update(
                output=output,
                usage=usage,
                cost_usd=cost_usd,
                metadata=metadata,
                status=status,
                error=error,
            )
        obs = self.observation
        obs.ended_at = _utcnow()
        obs.duration_ms = int((time.perf_counter() - obs._t0) * 1000)
        self.trace._end_lf(obs)


def start_trace(
    name: str = "chat",
    *,
    conversation_id: str | None = None,
    user_id: str | None = None,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
) -> TraceHandle | None:
    """Start a root trace and bind it to the current contextvar.

    Returns None when both internal tracing and Langfuse are inactive.
    """
    if not tracing_active():
        return None

    s = get_settings()
    handle = TraceHandle(
        id=_new_id(),
        name=name,
        conversation_id=conversation_id,
        user_id=user_id,
        started_at=_utcnow(),
        input_preview=preview_text(input, store_io=s.trace_store_io),
        metadata=dict(metadata or {}),
    )

    handle._lf_tags = build_langfuse_tags(name=name, metadata=handle.metadata)

    lf = get_langfuse()
    if lf is not None:
        try:
            lf_root = lf.start_observation(
                name=name,
                as_type="span",
                input=input if s.trace_store_io else None,
                metadata=handle.metadata,
            )
            handle._lf_root = lf_root
            handle._stamp_lf(lf_root)
        except Exception as exc:  # noqa: BLE001
            log.warning("langfuse_trace_start_failed", error=str(exc))

    handle._token = _current_trace.set(handle)
    return handle


def get_current_trace() -> TraceHandle | None:
    return _current_trace.get()


def get_current_trace_id() -> str | None:
    t = _current_trace.get()
    return t.id if t is not None else None


@contextmanager
def span(name: str, **kwargs: Any) -> Iterator[SpanHandle | None]:
    """Open a child span on the current trace (no-op when inactive)."""
    t = get_current_trace()
    if t is None:
        yield None
        return
    with t.span(name, **kwargs) as handle:
        yield handle


@asynccontextmanager
async def aspan(name: str, **kwargs: Any) -> AsyncIterator[SpanHandle | None]:
    t = get_current_trace()
    if t is None:
        yield None
        return
    async with t.span(name, **kwargs) as handle:
        yield handle


@asynccontextmanager
async def ageneration(name: str, **kwargs: Any) -> AsyncIterator[SpanHandle | None]:
    t = get_current_trace()
    if t is None:
        yield None
        return
    async with t.generation(name, **kwargs) as handle:
        yield handle


@asynccontextmanager
async def atool(name: str, **kwargs: Any) -> AsyncIterator[SpanHandle | None]:
    t = get_current_trace()
    if t is None:
        yield None
        return
    async with t.tool(name, **kwargs) as handle:
        yield handle


def _trace_value_summary(value: Any) -> Any:
    """Reduce large runtime objects to admin-safe IO previews."""
    if value is None:
        return None
    if hasattr(value, "trace_metadata") and callable(getattr(value, "trace_metadata")):
        return value.trace_metadata()
    if isinstance(value, dict):
        if "messages" in value and any(
            key in value for key in ("iterations", "pending_tool_calls", "final_report", "runtime_scope")
        ):
            pending = value.get("pending_tool_calls") or []
            tool_names: list[str] = []
            for item in pending:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or (item.get("function") or {}).get("name")
                if name:
                    tool_names.append(str(name))
            final_report = value.get("final_report")
            summary: dict[str, Any] = {
                "iterations": value.get("iterations"),
                "message_count": len(value.get("messages") or []),
                "pending_tools": tool_names,
            }
            if final_report:
                summary["final_report"] = str(final_report)[:500]
            if value.get("report_streamed") is not None:
                summary["report_streamed"] = bool(value.get("report_streamed"))
            runtime_scope = value.get("runtime_scope")
            if isinstance(runtime_scope, dict):
                summary["runtime_scope"] = {
                    "kind": runtime_scope.get("kind"),
                    "selected_kb_ids": runtime_scope.get("selected_kb_ids"),
                }
            return summary
        if "kind" in value and "selected_kb_ids" in value:
            return value
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_trace_value_summary(item) for item in list(value)[:20]]
    return str(value)[:500]


def traced(name: str, *, as_type: ObservationType = "span", capture_io: bool = True):
    """Decorator: wrap an async function in a named observation on the current trace."""

    def decorator(fn):
        async def wrapper(*args: Any, **kwargs: Any):
            t = get_current_trace()
            if t is None:
                return await fn(*args, **kwargs)
            input_summary = _trace_value_summary(args[0]) if capture_io and args else None
            async with t.start_observation(name, as_type=as_type, input=input_summary) as handle:
                try:
                    result = await fn(*args, **kwargs)
                    if capture_io and result is not None:
                        handle.update(output=_trace_value_summary(result))
                    return result
                except Exception as exc:
                    handle.update(error=str(exc), status="error")
                    raise

        wrapper.__name__ = getattr(fn, "__name__", name)
        wrapper.__qualname__ = getattr(fn, "__qualname__", name)
        return wrapper

    return decorator


def dump_trace_metadata(meta: dict[str, Any]) -> str | None:
    if not meta:
        return None
    return json.dumps(meta, ensure_ascii=False, default=str)
