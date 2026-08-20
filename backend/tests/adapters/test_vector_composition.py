"""Contract tests for configuration-driven vector backend composition."""
from __future__ import annotations

import pytest

from src.adapters.vector.composition import VectorStoreConfig, VectorStoreProvider


class _Store:
    async def ensure_collection(self, vector_size: int, **kwargs) -> None:
        _ = vector_size, kwargs

    async def upsert(self, points, **kwargs) -> None:
        _ = points, kwargs

    async def search(self, query_vector, **kwargs):
        _ = query_vector, kwargs
        return []


def _config(backend: str) -> VectorStoreConfig:
    return VectorStoreConfig(
        backend=backend,  # type: ignore[arg-type]
        qdrant_url="http://qdrant.example",
        qdrant_api_key="key",
        collection_name="default",
        milvus_uri="http://milvus.example:19530",
        milvus_token="token",
        local_db_path="/tmp/vector.db",
    )


@pytest.mark.parametrize("backend", ["qdrant", "milvus", "local"])
def test_provider_selects_the_requested_backend_and_caches_it(backend: str) -> None:
    built: list[str] = []
    stores = {name: _Store() for name in ("qdrant", "milvus", "local")}
    provider = VectorStoreProvider(
        builders={
            name: lambda config, name=name: built.append(name) or stores[name]
            for name in stores
        }
    )

    config = _config(backend)
    assert provider.get(config) is stores[backend]
    assert provider.get(config) is stores[backend]
    assert built == [backend]


def test_provider_reset_rebuilds_the_store() -> None:
    built: list[_Store] = []
    provider = VectorStoreProvider(
        builders={
            name: lambda config: built.append(_Store()) or built[-1]
            for name in ("qdrant", "milvus", "local")
        }
    )
    config = _config("qdrant")
    first = provider.get(config)
    provider.reset()
    second = provider.get(config)

    assert first is not second
    assert len(built) == 2
