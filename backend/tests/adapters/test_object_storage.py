"""Object-storage port and composition contract tests."""
from __future__ import annotations

import pytest

from src.adapters.files import LocalFileStorage, ObjectStorageConfig, ObjectStorageProvider
from src.adapters.files.s3 import S3FileStorage


class _Storage:
    async def put(self, key, content, *, content_type=None):
        _ = key, content, content_type

    async def get(self, key):
        _ = key
        return b""

    async def delete(self, key):
        _ = key

    async def delete_prefix(self, prefix):
        _ = prefix


def _config(backend: str) -> ObjectStorageConfig:
    return ObjectStorageConfig(
        backend=backend,  # type: ignore[arg-type]
        local_root="/tmp/uploads",
        bucket="documents",
        endpoint_url="http://minio.example",
        access_key_id="access",
        secret_access_key="secret",
        region="us-east-1",
    )


@pytest.mark.parametrize("backend", ["local", "s3"])
def test_object_storage_provider_selects_and_caches_backend(backend: str) -> None:
    built: list[str] = []
    stores = {name: _Storage() for name in ("local", "s3")}
    provider = ObjectStorageProvider(
        builders={
            name: lambda config, name=name: built.append(name) or stores[name]
            for name in stores
        }
    )
    config = _config(backend)

    assert provider.get(config) is stores[backend]
    assert provider.get(config) is stores[backend]
    assert built == [backend]


@pytest.mark.asyncio
async def test_local_storage_lifecycle_and_prefix_cleanup(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.put("kb-1/a.txt", b"a", content_type="text/plain")
    await storage.put("kb-1/nested/b.txt", b"b")
    assert await storage.get("kb-1/a.txt") == b"a"

    await storage.delete_prefix("kb-1/")
    with pytest.raises(FileNotFoundError):
        await storage.get("kb-1/a.txt")
    assert not (tmp_path / "kb-1").exists()


class _Body:
    def read(self) -> bytes:
        return b"remote"


class _S3Client:
    def __init__(self) -> None:
        self.deleted: list[dict] = []

    def put_object(self, **kwargs) -> None:
        self.put = kwargs

    def get_object(self, **kwargs):
        self.get = kwargs
        return {"Body": _Body()}

    def delete_object(self, **kwargs) -> None:
        self.deleted.append(kwargs)

    def list_objects_v2(self, **kwargs):
        self.list = kwargs
        return {"Contents": [{"Key": "kb-1/a"}], "IsTruncated": False}

    def delete_objects(self, **kwargs) -> None:
        self.deleted.append(kwargs)


@pytest.mark.asyncio
async def test_s3_storage_uses_bucket_and_prefix_contract() -> None:
    client = _S3Client()
    storage = S3FileStorage(bucket="documents", client=client)
    await storage.put("kb-1/a", b"data", content_type="text/plain")
    assert client.put["Bucket"] == "documents"
    assert client.put["Key"] == "kb-1/a"
    assert await storage.get("kb-1/a") == b"remote"

    await storage.delete_prefix("kb-1/")
    assert client.list == {"Bucket": "documents", "Prefix": "kb-1/"}
    assert client.deleted[-1]["Delete"]["Objects"] == [{"Key": "kb-1/a"}]
