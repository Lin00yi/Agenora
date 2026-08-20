"""Stable execution harness for every interactive AI run.

The harness owns runtime contracts and orchestration boundaries. Product
capabilities and infrastructure adapters are plugged into it; neither is
allowed to depend on HTTP delivery details.
"""

from .contracts.events import EventEmitter, RunEvent
from .contracts.runtime import RunContext, RunIdentity

__all__ = ["EventEmitter", "RunContext", "RunEvent", "RunIdentity"]
