"""Ports implemented by concrete infrastructure adapters."""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    """Minimal vector-query port shared by retrieval capabilities."""

    async def ensure_collection(self, vector_size: int, **kwargs: Any) -> None: ...
    async def upsert(self, points: list[dict[str, Any]], **kwargs: Any) -> None: ...
    async def search(self, query_vector: list[float], **kwargs: Any) -> list[dict[str, Any]]: ...


@runtime_checkable
class CollectionVectorStore(VectorStore, Protocol):
    """KB-capable vector port with isolated collection lifecycle."""

    async def create_collection(self, collection_name: str, vector_size: int) -> None: ...
    async def delete_collection(self, collection_name: str) -> None: ...
    async def delete_by_filter(self, collection_name: str, filters: dict[str, Any]) -> None: ...


@runtime_checkable
class ObjectStorage(Protocol):
    async def put(self, key: str, content: bytes, *, content_type: str | None = None) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...


@runtime_checkable
class LLMGateway(Protocol):
    def client_for(self, config: Any | None = None) -> Any: ...


@runtime_checkable
class TraceSink(Protocol):
    def record(self, name: str, *, metadata: dict[str, Any] | None = None) -> Awaitable[Any] | Any: ...
