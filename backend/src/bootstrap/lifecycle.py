"""FastAPI lifecycle backed by the application composition root."""
from __future__ import annotations

import logging
from asyncio import CancelledError, Task, create_task
from contextlib import suppress
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.bootstrap.container import build_container
from src.capabilities.identity.admin_seed import seed_admins
from src.capabilities.knowledge.application.system_seed import seed_system_kbs
from src.bootstrap.database import initialize_database
from src.harness.mcp.manager import close_mcp_manager

log = structlog.get_logger()


@asynccontextmanager
async def application_lifespan(app: FastAPI):
    """Attach the composed service container and initialize owned resources."""
    container = build_container()
    app.state.container = container
    logging.getLogger(__name__).info("startup", extra={"env": container.settings.app_env})
    log.info("startup", env=container.settings.app_env)
    await initialize_database()
    log.info("db_ready")
    await seed_system_kbs()
    log.info("system_kbs_ready")
    await seed_admins()
    log.info("admins_seeded")
    operation_worker_task: Task[None] | None = None
    # Local development commonly uses an embedded Milvus Lite file. A second
    # worker process cannot open that file while the API owns it, so run the
    # durable operation worker inside this process. Production Compose keeps
    # this disabled and starts its dedicated `operation-worker` service.
    if container.settings.app_env.strip().lower() != "prod":
        from src.bootstrap.workers.operations import worker_main

        operation_worker_task = create_task(
            worker_main(), name="agenora-local-operation-worker"
        )
        log.info("operation_worker_started", mode="in_process")
    try:
        yield
    finally:
        if operation_worker_task is not None:
            operation_worker_task.cancel()
            with suppress(CancelledError):
                await operation_worker_task
        await close_mcp_manager()
        log.info("shutdown")
