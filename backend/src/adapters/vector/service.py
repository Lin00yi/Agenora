"""Current vector implementation adapter.

The storage package remains a compatibility implementation detail while new
application code enters through this facade.
"""
from __future__ import annotations

from typing import Any

from src.storage.vector.embedding import _resolve_config, get_vector_size, probe_vector_size


def configured_vector_size() -> int:
    return get_vector_size()


async def probe_vector_dimension(config: Any | None = None) -> int:
    return await probe_vector_size(config)


def default_embedding_model() -> str:
    return str(_resolve_config()["model"])
