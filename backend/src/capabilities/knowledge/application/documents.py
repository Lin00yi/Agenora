"""Document lifecycle use cases for the knowledge capability.

The HTTP layer owns authorization and response formatting.  This module owns
the application-facing document/file operations so routes do not reach into
the legacy ingestion worker or its on-disk layout directly.
"""
from __future__ import annotations

from src.platform.files.object_storage import get_object_storage
def upload_key(kb_id: str, doc_id: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    ext = "".join(char for char in ext if char.isalnum())[:16] or "bin"
    return f"{kb_id}/{doc_id}.{ext}"


async def save_upload(
    kb_id: str,
    doc_id: str,
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
) -> None:
    key = upload_key(kb_id, doc_id, filename)
    await get_object_storage().put(key, content, content_type=content_type)


async def read_upload(kb_id: str, doc_id: str, filename: str) -> bytes:
    return await get_object_storage().get(upload_key(kb_id, doc_id, filename))


async def delete_upload(kb_id: str, doc_id: str, filename: str) -> None:
    await get_object_storage().delete(upload_key(kb_id, doc_id, filename))


async def delete_kb_uploads(kb_id: str) -> None:
    await get_object_storage().delete_prefix(f"{kb_id}/")


async def remove_document_chunks(collection_name: str, doc_id: str) -> None:
    """Delete vector and relational chunks through the ingestion use case."""
    from .ingestion import delete_document_chunks

    await delete_document_chunks(collection_name, doc_id)
