"""FastAPI routers."""

from src.api.routes.admin import router as admin_router
from src.api.routes.auth import router as auth_router
from src.api.routes.chat import router as chat_router
from src.api.routes.conversations import router as conversations_router
from src.api.routes.kb import router as kb_router
from src.api.routes.settings import router as settings_router

__all__ = [
    "admin_router",
    "auth_router",
    "chat_router",
    "conversations_router",
    "kb_router",
    "settings_router",
]
