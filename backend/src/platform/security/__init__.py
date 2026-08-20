"""Platform security primitives such as encryption at rest."""

from .crypto import decrypt, encrypt

__all__ = ["decrypt", "encrypt"]
