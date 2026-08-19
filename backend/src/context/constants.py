"""Shared constants and dataclasses for conversation context assembly."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.conversations.models import ConversationSummary

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
MAX_MEMORY_CONTEXT_TOKENS = 1_200
MAX_PROFILE_CONTEXT_TOKENS = 700
MAX_SUMMARY_CONTEXT_TOKENS = 2_600
MAX_SUMMARY_SOURCE_CHARS = 12_000
MAX_MEMORY_EXTRACTION_SOURCE_CHARS = 16_000
MAX_PROFILE_MEMORY_ROWS = 40
PREPARE_SUMMARY_RATIO = 0.60
SUMMARY_TRIGGER_RATIO = 0.72
FORCE_SUMMARY_RATIO = 0.85
# When writing a rolling summary, keep this many completed user/assistant
# turns as verbatim dialogue plus the current user message. Prompt assembly
# still injects every uncovered turn and only then trims by token budget;
# this constant must not drop rows that are not yet in the summary.
RECENT_TURNS = 20
MIN_RECENT_TURNS_ON_PRESSURE = 10
# Stable response preferences that belong in the always-on profile block.
# Query-retrieved memories exclude these ids so the same fact is not injected twice.
PROFILE_PREFERENCE_KEYS = frozenset(
    {"response_language", "response_style", "response_max_chars"}
)
# Hybrid memory recall: keep the gate strict so short off-topic queries
# (e.g. "还有什么卡？") do not pull high-importance unrelated facts.
MEMORY_SEMANTIC_MIN = 0.55
MEMORY_RETRIEVAL_LIMIT = 4
MEMORY_IMPORTANCE_WEIGHT = 0.25
MEMORY_CONFIDENCE_WEIGHT = 0.25
MEMORY_INJECT_DEDUPE_COSINE = 0.88
MEMORY_CONSOLIDATE_SEMANTIC = 0.88

SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?:密码|口令|验证码|动态码).{0,8}(?:是|为|[:：=])\s*\S{4,}"),
    re.compile(r"\b\d{15,18}[\dXx]\b"),
    re.compile(r"\b\d{13,19}\b"),
]


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


@dataclass(frozen=True)
class MemoryCandidate:
    """A high-confidence memory inferred from one user-authored message."""

    type: str
    key: str
    value: str
    content: str
    confidence: float
    importance: float
    source: str
    scope: str = "personal"
    expires_in_days: int | None = None
