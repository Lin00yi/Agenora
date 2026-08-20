"""Object/file storage adapters."""

from .local import LocalFileStorage
from .s3 import S3FileStorage
from .composition import (
    ObjectStorageConfig,
    ObjectStorageProvider,
    get_object_storage,
    reset_object_storage,
)

__all__ = [
    "LocalFileStorage", "ObjectStorageConfig", "ObjectStorageProvider",
    "S3FileStorage", "get_object_storage", "reset_object_storage",
]
