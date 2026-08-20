import asyncio

from sqlalchemy import text

from src.bootstrap.database import initialize_database
from src.platform.persistence.database import get_session_factory


async def main() -> None:
    await initialize_database()
    async with get_session_factory()() as s:
        r = await s.execute(
            text(
                "select id, name, status, conversation_id, user_id, started_at, "
                "duration_ms from traces order by started_at desc"
            )
        )
        rows = list(r)
        print("trace_count", len(rows))
        for row in rows:
            print(dict(row._mapping))


if __name__ == "__main__":
    asyncio.run(main())
