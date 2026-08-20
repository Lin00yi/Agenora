"""Configuration-driven object-storage composition root."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from src.harness.contracts.protocols import ObjectStorage
from src.settings import get_settings

from .local import LocalFileStorage
from .s3 import S3FileStorage


StorageBackend = Literal["local", "s3"]
StorageBuilder = Callable[["ObjectStorageConfig"], ObjectStorage]


@dataclass(frozen=True)
class ObjectStorageConfig:
    backend: StorageBackend
    local_root: str
    bucket: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    region: str

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> "ObjectStorageConfig":
        settings = settings or get_settings()
        backend = str(settings.object_storage or "local").lower()
        if backend not in {"local", "s3"}:
            raise ValueError("OBJECT_STORAGE must be 'local' or 's3'.")
        if backend == "s3" and not settings.object_storage_bucket:
            raise ValueError("OBJECT_STORAGE_BUCKET is required when OBJECT_STORAGE=s3.")
        return cls(
            backend=backend,  # type: ignore[arg-type]
            local_root=settings.object_storage_local_root,
            bucket=settings.object_storage_bucket,
            endpoint_url=settings.object_storage_endpoint_url,
            access_key_id=settings.object_storage_access_key_id,
            secret_access_key=settings.object_storage_secret_access_key,
            region=settings.object_storage_region,
        )


class ObjectStorageProvider:
    def __init__(self, builders: dict[StorageBackend, StorageBuilder] | None = None) -> None:
        self._builders = builders or {"local": self._build_local, "s3": self._build_s3}
        self._cache: dict[ObjectStorageConfig, ObjectStorage] = {}

    def get(self, config: ObjectStorageConfig | None = None) -> ObjectStorage:
        config = config or ObjectStorageConfig.from_settings()
        if config not in self._cache:
            self._cache[config] = self._builders[config.backend](config)
        return self._cache[config]

    def reset(self) -> None:
        self._cache.clear()

    @staticmethod
    def _build_local(config: ObjectStorageConfig) -> ObjectStorage:
        return LocalFileStorage(Path(config.local_root))

    @staticmethod
    def _build_s3(config: ObjectStorageConfig) -> ObjectStorage:
        return S3FileStorage.from_config(
            bucket=config.bucket,
            endpoint_url=config.endpoint_url,
            access_key_id=config.access_key_id,
            secret_access_key=config.secret_access_key,
            region=config.region,
        )


_provider = ObjectStorageProvider()


def get_object_storage(config: ObjectStorageConfig | None = None) -> ObjectStorage:
    return _provider.get(config)


def reset_object_storage() -> None:
    _provider.reset()
