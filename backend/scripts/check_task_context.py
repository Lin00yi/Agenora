"""Login as admin and hit /api/chat; then count new traces."""
from __future__ import annotations

import asyncio

from sqlalchemy import text


async def main() -> None:
    from src.bootstrap.database import initialize_database
    from src.platform.persistence.database import get_session_factory

    await initialize_database()
    email = None
    async with get_session_factory()() as s:
        row = (
            await s.execute(
                text(
                    "select email from users where is_admin = true order by created_at limit 1"
                )
            )
        ).first()
        if not row:
            raise SystemExit("no admin user")
        email = row[0]
        before = int((await s.execute(text("select count(*) from traces"))).scalar_one())
    print("admin", email, "traces_before", before)

    # Password unknown — use internal smoke that mirrors chat finish path instead.
    # Simulate the exact create_task + contextvar pattern from app.py.
    from src.platform.observability import get_current_trace, start_trace

    handle = start_trace(
        "chat_task_sim",
        conversation_id="sim",
        user_id="sim-user",
        input="simulate",
    )
    assert handle is not None
    started_id = handle.id
    print("started_in_parent", started_id)

    async def run_agent() -> None:
        trace = get_current_trace()
        print(
            "in_task",
            None if trace is None else trace.id,
            "same",
            trace is handle if trace else False,
        )
        if trace is None:
            trace = start_trace("chat_task_sim_fallback", input="fallback")
        with trace.span("node_reason") as sp:
            sp.end(output="ok")
        await trace.finish(status="ok", output="report")
        print("finished_in_task", trace.id)

    task = asyncio.create_task(run_agent())
    await task

    async with get_session_factory()() as s:
        after = int((await s.execute(text("select count(*) from traces"))).scalar_one())
        row = (
            await s.execute(
                text("select id, name from traces where id = :id"),
                {"id": started_id},
            )
        ).first()
    print("traces_after", after, "persisted_started", bool(row))
    print("ok" if row else "FAIL_CONTEXT_OR_PERSIST")


if __name__ == "__main__":
    asyncio.run(main())
