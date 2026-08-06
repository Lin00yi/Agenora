"""Smoke test: internal trace persist + toggle off."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path


async def main() -> None:
    # Isolate DB for this smoke test.
    tmp = Path(tempfile.mkdtemp()) / "trace_smoke.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp.as_posix()}"
    os.environ["TRACE_ENABLED"] = "true"
    os.environ["LANGFUSE_ENABLED"] = "false"
    os.environ["JWT_SECRET"] = "test-secret"

    from src.settings import get_settings

    get_settings.cache_clear()

    from src.infra.database import init_db, get_session_factory
    from src.observability import start_trace, get_current_trace_id
    from src.observability.models import Trace, Observation
    from sqlalchemy import select, func

    await init_db()

    trace = start_trace(
        "chat",
        conversation_id="conv-1",
        user_id="user-1",
        input="hello",
        metadata={"kb_id": None},
    )
    assert trace is not None
    assert get_current_trace_id() == trace.id

    with trace.span("build_context"):
        with trace.generation("llm.chat_with_tools", model="test-model", input="hi") as gen:
            gen.update(output="world", usage={"input_tokens": 1, "output_tokens": 2}, cost_usd=0.001)
        with trace.tool("web_search", input={"q": "x"}) as tool:
            tool.update(output="ok")

    await trace.finish(status="ok", output="final", total_cost_usd=0.001)

    factory = get_session_factory()
    async with factory() as session:
        tcount = int((await session.execute(select(func.count()).select_from(Trace))).scalar_one())
        ocount = int(
            (await session.execute(select(func.count()).select_from(Observation))).scalar_one()
        )
        row = await session.get(Trace, trace.id)
        assert row is not None
        assert row.duration_ms is not None and row.duration_ms >= 0
        assert tcount == 1
        assert ocount == 3  # build_context + generation + tool
        print("persist_ok", {"trace_id": trace.id, "duration_ms": row.duration_ms, "obs": ocount})

    # Toggle off
    os.environ["TRACE_ENABLED"] = "false"
    get_settings.cache_clear()
    from src.observability.langfuse_client import reset_langfuse_for_tests

    reset_langfuse_for_tests()
    from src.observability import tracing_active, start_trace as st2

    assert tracing_active() is False
    assert st2("chat") is None
    print("toggle_off_ok")


if __name__ == "__main__":
    asyncio.run(main())
