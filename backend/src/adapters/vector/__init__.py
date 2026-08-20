"""Vector-store adapter facade."""

from .service import (
    configured_vector_size,
    default_embedding_model,
    probe_vector_dimension,
)
from .composition import (
    VectorStoreConfig,
    VectorStoreProvider,
    get_vector_store,
    reset_vector_store,
)

__all__ = [
    "configured_vector_size",
    "default_embedding_model",
    "get_vector_store",
    "probe_vector_dimension",
    "reset_vector_store",
    "VectorStoreConfig",
    "VectorStoreProvider",
]
