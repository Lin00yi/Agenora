"""FastAPI application factory.

HTTP routes live under ``src.api``; this module only wires middleware, lifespan,
and routers. Uvicorn still loads ``src.app:app``.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.admin import router as admin_router
from src.api.routes.chat import router as chat_router
from src.api.routes.auth import router as auth_router
from src.api.routes.conversations import router as conversations_router
from src.api.routes.kb import router as kb_router
from src.bootstrap.lifecycle import application_lifespan
from src.settings import get_settings
from src.api.routes.settings import router as settings_router

APP_VERSION = "3.1.0"


def create_app() -> FastAPI:
    application = FastAPI(title="Agenora", version=APP_VERSION, lifespan=application_lifespan)
    settings = get_settings()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST", "DELETE", "PATCH"],
        allow_headers=["*"],
    )
    application.include_router(auth_router)
    application.include_router(kb_router)
    application.include_router(conversations_router)
    application.include_router(settings_router)
    application.include_router(admin_router)
    application.include_router(chat_router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    return application


app = create_app()
