import asyncio
from sqlalchemy import text, select, func
from src.storage.database import get_session_factory, init_db
from src.observability.models import Trace, Observation

async def main():
    await init_db()
    f = get_session_factory()
    async with f() as s:
        tables = (await s.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename IN ('traces','observations')"
        ))).fetchall()
        print("tables", [t[0] for t in tables])
        tc = int((await s.execute(select(func.count()).select_from(Trace))).scalar_one())
        oc = int((await s.execute(select(func.count()).select_from(Observation))).scalar_one())
        print("trace_count", tc, "obs_count", oc)
        rows = (await s.execute(select(Trace).order_by(Trace.started_at.desc()).limit(5))).scalars().all()
        for r in rows:
            print("trace", r.id[:12], r.name, r.status, r.duration_ms, r.conversation_id)

asyncio.run(main())
