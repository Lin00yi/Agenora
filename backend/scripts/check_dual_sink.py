"""Verify dual sink: DB persist + Langfuse from inside the running container."""
from __future__ import annotations

import asyncio
import os


async def main() -> None:
    from src.settings import get_settings

    get_settings.cache_clear()
    s = get_settings()
    print(
        "settings",
        {
            "trace_enabled": s.trace_enabled,
            "langfuse_enabled": s.langfuse_enabled,
            "langfuse_host": s.langfuse_host,
            "has_pk": bool(s.langfuse_public_key),
            "has_sk": bool(s.langfuse_secret_key),
        },
    )

    from src.infra.database import get_session_factory, init_db
    from src.observability import start_trace
    from src.observability.langfuse_client import get_langfuse
    from sqlalchemy import text

    await init_db()
    lf = get_langfuse()
    print("langfuse_client", type(lf).__name__ if lf else None)

    before = 0
    async with get_session_factory()() as session:
        before = int(
            (await session.execute(text("select count(*) from traces"))).scalar_one()
        )
    print("traces_before", before)

    handle = start_trace(
        "dual_sink_smoke",
        conversation_id="smoke-conv",
        user_id="smoke-user",
        input="hello dual sink",
        metadata={"source": "check_dual_sink"},
    )
    print("handle", None if handle is None else handle.id)
    if handle is None:
        raise SystemExit("start_trace returned None")

    with handle.span("smoke_child", input="child-in") as child:
        child.end(output="child-out")

    await handle.finish(status="ok", output="done")
    print("finished", handle.id)

    async with get_session_factory()() as session:
        after = int(
            (await session.execute(text("select count(*) from traces"))).scalar_one()
        )
        row = (
            await session.execute(
                text(
                    "select id, name, status, duration_ms from traces where id = :id"
                ),
                {"id": handle.id},
            )
        ).first()
        obs = int(
            (
                await session.execute(
                    text(
                        "select count(*) from observations where trace_id = :id"
                    ),
                    {"id": handle.id},
                )
            ).scalar_one()
        )
    print("traces_after", after, "delta", after - before)
    print("row", dict(row._mapping) if row else None)
    print("obs_count", obs)
    print("ok" if row and after == before + 1 else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
