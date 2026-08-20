"""FastAPI lifecycle backed by the application composition root."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.bootstrap.container import build_container
from src.capabilities.identity.admin_seed import seed_admins
from src.capabilities.knowledge.application.system_seed import seed_system_kbs
from src.bootstrap.database import initialize_database

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
    yield
    log.info("shutdown")
