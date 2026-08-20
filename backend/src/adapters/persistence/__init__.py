"""Persistence adapter facade."""

from .sqlalchemy import get_session, get_session_factory

__all__ = ["get_session", "get_session_factory"]
