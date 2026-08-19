"""Compatibility shim — use ``src.infra.vector.embedding`` instead."""

from __future__ import annotations

import sys

from src.infra.vector import embedding as _impl

sys.modules[__name__] = _impl
import src.infra as _pkg

_pkg.embedding = _impl
