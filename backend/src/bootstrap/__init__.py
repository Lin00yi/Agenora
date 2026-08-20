"""Application composition root and lifecycle wiring."""

from .container import ApplicationContainer, build_container

__all__ = ["ApplicationContainer", "build_container"]
