"""Configuration-driven composition root for vector backends.

The application selects a backend here.  Concrete Qdrant/Milvus classes stay
behind this boundary, while legacy ``src.platform.vector.get_store`` forwards
here until all old imports are retired.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from src.harness.contracts.protocols import VectorStore
from src.settings import get_settings


VectorBackend = Literal["qdrant", "milvus", "local"]
StoreBuilder = Callable[["VectorStoreConfig"], VectorStore]


@dataclass(frozen=True)
class VectorStoreConfig:
    backend: VectorBackend
    qdrant_url: str
    qdrant_api_key: str
    collection_name: str
    milvus_uri: str
    milvus_token: str
    local_db_path: str

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> "VectorStoreConfig":
        settings = settings or get_settings()
        backend = str(settings.vector_store or "qdrant").lower()
        if backend not in {"qdrant", "milvus", "local"}:
            raise ValueError(
                f"Unknown VECTOR_STORE='{backend}'. Supported: 'qdrant', 'milvus', 'local'."
            )
        return cls(
            backend=backend,  # type: ignore[arg-type]
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            collection_name=settings.qdrant_collection,
            milvus_uri=settings.milvus_uri,
            milvus_token=settings.milvus_token,
            local_db_path=settings.local_vector_db_path,
        )


class VectorStoreProvider:
    """Caches one configured backend and supports explicit test injection."""

    def __init__(self, builders: dict[VectorBackend, StoreBuilder] | None = None) -> None:
        self._builders = builders or {
            "qdrant": self._build_qdrant,
            "milvus": self._build_milvus,
            "local": self._build_local,
        }
        self._cache: dict[VectorStoreConfig, VectorStore] = {}

    def get(self, config: VectorStoreConfig | None = None) -> VectorStore:
        config = config or VectorStoreConfig.from_settings()
        if config not in self._cache:
            self._cache[config] = self._builders[config.backend](config)
        return self._cache[config]

    def reset(self) -> None:
        self._cache.clear()

    @staticmethod
    def _build_qdrant(config: VectorStoreConfig) -> VectorStore:
        from src.platform.vector.store import QdrantStore

        return QdrantStore(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key,
            collection_name=config.collection_name,
        )

    @staticmethod
    def _build_milvus(config: VectorStoreConfig) -> VectorStore:
        from src.platform.vector.store import MilvusStore

        return MilvusStore(
            uri=config.milvus_uri,
            token=config.milvus_token,
            collection_name=config.collection_name,
        )

    @staticmethod
    def _build_local(config: VectorStoreConfig) -> VectorStore:
        from src.platform.vector.local import LocalVectorStore

        return LocalVectorStore(db_path=config.local_db_path)


_provider = VectorStoreProvider()


def get_vector_store(config: VectorStoreConfig | None = None) -> VectorStore:
    return _provider.get(config)


def reset_vector_store() -> None:
    _provider.reset()
