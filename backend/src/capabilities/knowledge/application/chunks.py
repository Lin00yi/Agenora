"""Chunk-editing use cases behind the knowledge capability boundary.

Chunk persistence and vector synchronization remain in the mature domain
service for now; this facade gives delivery code one stable capability API.
"""
from src.kb.chunk_service import (
    batch_set_all_document_chunks_enabled,
    batch_set_chunks_enabled,
    delete_single_chunk,
    list_document_chunks_with_backfill,
    merge_chunks,
    split_chunk,
    sync_chunk_payloads_only,
    sync_document_vector_payloads,
    upsert_single_chunk_vector,
)

__all__ = [
    "batch_set_all_document_chunks_enabled",
    "batch_set_chunks_enabled",
    "delete_single_chunk",
    "list_document_chunks_with_backfill",
    "merge_chunks",
    "split_chunk",
    "sync_chunk_payloads_only",
    "sync_document_vector_payloads",
    "upsert_single_chunk_vector",
]
