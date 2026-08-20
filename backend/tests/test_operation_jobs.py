from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.platform.persistence.database import Base
from src.platform.tasks import service
from src.platform.tasks.models import OperationJob


@pytest.mark.asyncio
async def test_operation_job_deduplicates_active_work_and_moves_failed_work_to_dead_letter(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(service, "get_session_factory", lambda: factory)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            first = await service.enqueue_operation(
                session,
                kind="unknown_operation",
                payload={"safe": True},
                idempotency_key="same-request",
                max_attempts=1,
            )
            duplicate = await service.enqueue_operation(
                session,
                kind="unknown_operation",
                payload={"safe": True},
                idempotency_key="same-request",
                max_attempts=1,
            )
            await session.commit()
            assert duplicate.id == first.id

        assert await service.run_operation_job(first.id) is True
        async with factory() as session:
            row = await session.get(OperationJob, first.id)
            assert row is not None
            assert row.status == "dead_letter"
            assert row.attempts == 1
            assert "unknown operation kind" in row.error
    finally:
        await engine.dispose()
