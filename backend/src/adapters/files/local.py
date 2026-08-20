"""Local filesystem implementation of the object-storage port."""
from __future__ import annotations

from pathlib import Path


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root.resolve() not in candidate.parents and candidate != self.root.resolve():
            raise ValueError("file key escapes storage root")
        return candidate

    def path_for(self, key: str) -> Path:
        """Resolve a storage key for controlled local download responses."""
        return self._path(key)

    async def put(self, key: str, content: bytes, *, content_type: str | None = None) -> None:
        _ = content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    async def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    async def delete_prefix(self, prefix: str) -> None:
        """Delete a tenant/KB prefix without allowing a caller to escape root."""
        base = self._path(prefix.rstrip("/"))
        if not base.exists():
            return
        for path in sorted(base.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()
        if base.is_dir():
            base.rmdir()
