"""Compatibility shim — use ``src.infra.vector.local`` instead."""

from __future__ import annotations

import sys

from src.infra.vector import local as _impl

sys.modules[__name__] = _impl
import src.infra as _pkg

_pkg.local_vector = _impl
