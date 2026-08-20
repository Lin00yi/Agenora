"""Composition root for concrete platform services.

Only bootstrap code is allowed to know both harness contracts and concrete
platform implementations.  The container is intentionally small: existing
request handlers can migrate to explicit dependency injection without making
the current global provider APIs a second source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.platform.files.object_storage import get_object_storage
from src.platform.vector import get_vector_store
from src.settings import Settings, get_settings


@dataclass(frozen=True)
class ApplicationContainer:
    """Configured platform services for one Agenora process."""

    settings: Settings

    def vector_store(self):
        return get_vector_store()

    def object_storage(self):
        return get_object_storage()


def build_container(settings: Settings | None = None) -> ApplicationContainer:
    return ApplicationContainer(settings=settings or get_settings())
