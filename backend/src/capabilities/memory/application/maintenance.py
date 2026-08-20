"""Bounded user-memory maintenance application use case."""

from typing import Any


async def run_maintenance(**kwargs: Any) -> Any:
    from src.storage.jobs.memory import run_memory_maintenance

    return await run_memory_maintenance(**kwargs)
