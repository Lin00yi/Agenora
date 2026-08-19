"""Compatibility shim — use ``src.infra.jobs.memory`` instead."""

from __future__ import annotations

import sys

from src.infra.jobs import memory as _impl

sys.modules[__name__] = _impl
import src.infra as _pkg

_pkg.memory_maintenance = _impl
