"""Compatibility shim — use ``src.infra.vector.store`` instead."""

from __future__ import annotations

import sys

from src.infra.vector import store as _impl

sys.modules[__name__] = _impl
import src.infra as _pkg

_pkg.vector_store = _impl
