"""Unit tests for Langfuse trace-attribute stamping (Trace Name / Tags / Env)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.observability.langfuse_client import (
    build_langfuse_tags,
    resolve_langfuse_environment,
    stamp_langfuse_trace_attrs,
)


class _FakeOtelSpan:
    def __init__(self) -> None:
        self.attrs: dict = {}

    def is_recording(self) -> bool:
        return True

    def set_attributes(self, attrs: dict) -> None:
        self.attrs.update(attrs)

    def set_attribute(self, key: str, value: object) -> None:
        self.attrs[key] = value


def test_build_langfuse_tags_kb_and_model() -> None:
    assert build_langfuse_tags(
        name="chat", metadata={"kb_id": "kb-1", "model": "deepseek-v4-flash"}
    ) == ["chat", "kb", "model:deepseek-v4-flash"]


def test_build_langfuse_tags_general() -> None:
    assert build_langfuse_tags(name="chat", metadata={}) == ["chat", "general"]


def test_resolve_langfuse_environment_from_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.observability import langfuse_client as lc

    monkeypatch.setattr(
        lc,
        "get_settings",
        lambda: SimpleNamespace(app_env="prod", langfuse_tracing_environment=""),
    )
    assert resolve_langfuse_environment() == "production"

    monkeypatch.setattr(
        lc,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="dev", langfuse_tracing_environment="staging"
        ),
    )
    assert resolve_langfuse_environment() == "staging"


def test_stamp_sets_trace_name_tags_user_session() -> None:
    from langfuse._client.attributes import LangfuseOtelSpanAttributes

    otel = _FakeOtelSpan()
    lf_obs = SimpleNamespace(_otel_span=otel)
    stamp_langfuse_trace_attrs(
        lf_obs,
        trace_name="chat",
        user_id="user-1",
        session_id="conv-1",
        tags=["chat", "kb"],
        metadata={"kb_id": "kb-1", "model": "m1"},
        environment="production",
    )
    assert otel.attrs[LangfuseOtelSpanAttributes.TRACE_NAME] == "chat"
    assert otel.attrs[LangfuseOtelSpanAttributes.TRACE_USER_ID] == "user-1"
    assert otel.attrs[LangfuseOtelSpanAttributes.TRACE_SESSION_ID] == "conv-1"
    assert otel.attrs[LangfuseOtelSpanAttributes.TRACE_TAGS] == ["chat", "kb"]
    assert otel.attrs[LangfuseOtelSpanAttributes.ENVIRONMENT] == "production"
    assert (
        otel.attrs[f"{LangfuseOtelSpanAttributes.TRACE_METADATA}.kb_id"] == "kb-1"
    )
