"""Initialize LangGraph's isolated checkpoint schema before API replicas start."""
from __future__ import annotations

import asyncio

from src.harness.runtime.checkpoints import open_agent_checkpointer


async def main() -> None:
    async with open_agent_checkpointer():
        # ``open_agent_checkpointer`` performs idempotent saver setup.
        return


if __name__ == "__main__":
    asyncio.run(main())
