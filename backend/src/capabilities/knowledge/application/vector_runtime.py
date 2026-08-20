"""Knowledge capability's vector operations through the adapter port."""

from src.adapters.vector import (
    configured_vector_size,
    default_embedding_model,
    get_vector_store,
    probe_vector_dimension,
)

__all__ = [
    "configured_vector_size",
    "default_embedding_model",
    "get_vector_store",
    "probe_vector_dimension",
]
