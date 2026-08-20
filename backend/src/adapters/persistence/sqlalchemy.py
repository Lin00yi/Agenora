"""SQLAlchemy adapter compatibility facade."""

from src.storage.database import get_session, get_session_factory

__all__ = ["get_session", "get_session_factory"]
