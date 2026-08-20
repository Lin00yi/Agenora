"""Composition root for concrete platform services.

Only bootstrap code knows concrete factories. Request handlers and the agent
runtime receive this small interface instead of reaching for environment
settings or singleton factories directly; legacy callers remain supported
while capabilities migrate incrementally.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from src.platform.files.object_storage import get_object_storage
from src.platform.persistence import get_session_factory
from src.platform.vector import get_vector_store
from src.settings import Settings, get_settings


@dataclass(frozen=True)
class ApplicationContainer:
    """Configured platform ports for one Agenora process."""

    settings: Settings
    vector_store_factory: Callable[[], Any] = get_vector_store
    object_storage_factory: Callable[[], Any] = get_object_storage
    session_factory_provider: Callable[[], Any] = get_session_factory
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def vector_store(self):
        return self.vector_store_factory()

    def object_storage(self):
        return self.object_storage_factory()

    def session_factory(self):
        return self.session_factory_provider()


def build_container(settings: Settings | None = None) -> ApplicationContainer:
    return ApplicationContainer(settings=settings or get_settings())
