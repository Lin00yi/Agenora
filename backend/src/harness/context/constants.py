"""Shared constants and dataclasses for conversation context assembly."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.capabilities.conversations.models import ConversationSummary
from src.capabilities.memory.domain.policy import (
    MAX_ACTIVE_MEMORIES_PER_SCOPE as MAX_ACTIVE_MEMORIES_PER_SCOPE,
    MAX_MEMORY_CONTEXT_TOKENS as MAX_MEMORY_CONTEXT_TOKENS,
    MAX_MEMORY_EXTRACTION_SOURCE_CHARS as MAX_MEMORY_EXTRACTION_SOURCE_CHARS,
    MAX_PROFILE_MEMORY_ROWS as MAX_PROFILE_MEMORY_ROWS,
    MEMORY_CONFIDENCE_WEIGHT as MEMORY_CONFIDENCE_WEIGHT,
    MEMORY_CONSOLIDATE_SEMANTIC as MEMORY_CONSOLIDATE_SEMANTIC,
    MEMORY_IMPORTANCE_WEIGHT as MEMORY_IMPORTANCE_WEIGHT,
    MEMORY_INJECT_DEDUPE_COSINE as MEMORY_INJECT_DEDUPE_COSINE,
    MEMORY_RETRIEVAL_LIMIT as MEMORY_RETRIEVAL_LIMIT,
    MEMORY_SEMANTIC_MIN as MEMORY_SEMANTIC_MIN,
    MemoryCandidate as MemoryCandidate,
    PROFILE_PREFERENCE_KEYS as PROFILE_PREFERENCE_KEYS,
    SENSITIVE_PATTERNS as SENSITIVE_PATTERNS,
)

# BYOK accepts arbitrary model identifiers. Treat an unknown model
# conservatively instead of assuming DeepSeek's 64k window and overflowing a
# smaller OpenAI-compatible deployment.
DEFAULT_CONTEXT_WINDOW = 16_000
DEFAULT_OUTPUT_TOKENS = 4_096
MAX_OUTPUT_TOKENS = DEFAULT_OUTPUT_TOKENS
MIN_OUTPUT_TOKENS = 512
OUTPUT_TOKEN_HARD_CAP = 16_384
OUTPUT_TASK_TARGETS: dict[str, int] = {
    "answer": 2_048,
    "long_answer": 4_096,
    "report": 8_192,
}
SYSTEM_AND_TOOL_RESERVE = 6_000
RAG_RESERVE = 8_000
SAFETY_RESERVE = 2_000
MAX_PROFILE_CONTEXT_TOKENS = 700
MAX_SUMMARY_CONTEXT_TOKENS = 2_600
MAX_SUMMARY_SOURCE_CHARS = 12_000
# A user can keep a much larger archive, but only this many current records may
# remain eligible for prompt recall in one scope.  Without an explicit active
# set limit, ``retrieve_user_memories`` silently stopped considering old rows
# after its bounded candidate query.
PREPARE_SUMMARY_RATIO = 0.60
SUMMARY_TRIGGER_RATIO = 0.72
FORCE_SUMMARY_RATIO = 0.85
# When writing a rolling summary, keep this many completed user/assistant
# turns as verbatim dialogue plus the current user message. Prompt assembly
# still injects every uncovered turn and only then trims by token budget;
# this constant must not drop rows that are not yet in the summary.
RECENT_TURNS = 20
MIN_RECENT_TURNS_ON_PRESSURE = 10

@dataclass
class ContextBudget:
    model: str | None
    context_window: int
    available_history_tokens: int
    current_history_tokens: int
    ratio: float
    should_prepare_summary: bool
    should_summarize: bool
    force_summarize: bool


@dataclass
class BuiltContext:
    messages: list[dict[str, str]]
    budget: ContextBudget
    summary: ConversationSummary | None
    injected_memory_count: int
    memory_trace: dict[str, Any]
