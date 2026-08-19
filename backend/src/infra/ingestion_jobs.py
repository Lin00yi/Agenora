"""Compatibility shim — use ``src.infra.jobs.ingestion`` instead."""

from __future__ import annotations

import sys

from src.infra.jobs import ingestion as _impl

sys.modules[__name__] = _impl
import src.infra as _pkg

_pkg.ingestion_jobs = _impl
