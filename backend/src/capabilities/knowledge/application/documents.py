"""Document lifecycle use cases for the knowledge capability.

The HTTP layer owns authorization and response formatting.  This module owns
the application-facing document/file operations so routes do not reach into
the legacy ingestion worker or its on-disk layout directly.
"""
from __future__ import annotations

from pathlib import Path

from src.adapters.files import LocalFileStorage


UPLOAD_ROOT = Path(__file__).resolve().parents[4] / "data" / "uploads"
_storage = LocalFileStorage(UPLOAD_ROOT)


def upload_key(kb_id: str, doc_id: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    ext = "".join(char for char in ext if char.isalnum())[:16] or "bin"
    return f"{kb_id}/{doc_id}.{ext}"


def uploaded_path(kb_id: str, doc_id: str, filename: str) -> Path:
    """Return the local serving path without exposing the storage root."""
    return _storage.path_for(upload_key(kb_id, doc_id, filename))


async def save_upload(kb_id: str, doc_id: str, filename: str, content: bytes, *, content_type: str | None = None) -> Path:
    key = upload_key(kb_id, doc_id, filename)
    await _storage.put(key, content, content_type=content_type)
    return _storage.path_for(key)


async def delete_upload(kb_id: str, doc_id: str, filename: str) -> None:
    await _storage.delete(upload_key(kb_id, doc_id, filename))


async def delete_kb_uploads(kb_id: str) -> None:
    await _storage.delete_prefix(f"{kb_id}/")


async def remove_document_chunks(collection_name: str, doc_id: str) -> None:
    """Delete vector and relational chunks through the existing worker service."""
    from src.kb.ingest import delete_document_chunks

    await delete_document_chunks(collection_name, doc_id)
