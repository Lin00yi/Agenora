"""Ports implemented by concrete infrastructure adapters."""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    async def search(self, *args: Any, **kwargs: Any) -> Any: ...


@runtime_checkable
class ObjectStorage(Protocol):
    async def put(self, key: str, content: bytes, *, content_type: str | None = None) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


@runtime_checkable
class LLMGateway(Protocol):
    def client_for(self, config: Any | None = None) -> Any: ...


@runtime_checkable
class TraceSink(Protocol):
    def record(self, name: str, *, metadata: dict[str, Any] | None = None) -> Awaitable[Any] | Any: ...
