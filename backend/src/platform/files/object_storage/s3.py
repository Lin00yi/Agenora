"""Optional S3/MinIO implementation of the object-storage port."""
from __future__ import annotations

import asyncio
from typing import Any


class S3FileStorage:
    """S3-compatible storage backed by a synchronous boto3 client.

    boto3 is deliberately imported only when this backend is selected so local
    development keeps the existing dependency footprint.
    """

    def __init__(self, *, bucket: str, client: Any) -> None:
        self.bucket = bucket
        self._client = client

    @classmethod
    def from_config(
        cls,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
    ) -> "S3FileStorage":
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depends on deployment choice
            raise RuntimeError(
                "OBJECT_STORAGE=s3 requires optional dependency boto3. "
                "Install it with `pip install boto3`."
            ) from exc
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            region_name=region or None,
        )
        return cls(bucket=bucket, client=client)

    async def put(self, key: str, content: bytes, *, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(
            self._client.put_object, Bucket=self.bucket, Key=key, Body=content, **extra
        )

    async def get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self.bucket, Key=key
            )
        except Exception as exc:  # provider exception type is optional at runtime
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(key) from exc
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def delete_prefix(self, prefix: str) -> None:
        continuation: str | None = None
        while True:
            args: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
            if continuation:
                args["ContinuationToken"] = continuation
            page = await asyncio.to_thread(self._client.list_objects_v2, **args)
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                await asyncio.to_thread(
                    self._client.delete_objects,
                    Bucket=self.bucket,
                    Delete={"Objects": keys, "Quiet": True},
                )
            if not page.get("IsTruncated"):
                return
            continuation = page.get("NextContinuationToken")
