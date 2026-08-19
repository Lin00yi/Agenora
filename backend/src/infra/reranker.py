"""Compatibility shim — use ``src.infra.vector.reranker`` instead."""

from __future__ import annotations

import sys

from src.infra.vector import reranker as _impl

sys.modules[__name__] = _impl
import src.infra as _pkg

_pkg.reranker = _impl
