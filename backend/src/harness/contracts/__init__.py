"""Framework-independent contracts shared by the harness and capabilities."""

from .events import EventEmitter, RunEvent, RunEventKind
from .protocols import CollectionVectorStore, LLMGateway, ObjectStorage, TraceSink, VectorStore
from .runtime import RunContext, RunIdentity
from .state import AgentState, RetrievedEvidence, ToolCallRecord

__all__ = [
    "AgentState",
    "CollectionVectorStore",
    "EventEmitter",
    "LLMGateway",
    "ObjectStorage",
    "RetrievedEvidence",
    "RunContext",
    "RunEvent",
    "RunEventKind",
    "RunIdentity",
    "ToolCallRecord",
    "TraceSink",
    "VectorStore",
]
