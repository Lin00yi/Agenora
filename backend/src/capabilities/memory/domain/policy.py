"""Dependency-light policy types shared by memory extraction and context assembly."""
from __future__ import annotations

import re
from dataclasses import dataclass


MAX_MEMORY_EXTRACTION_SOURCE_CHARS = 16_000
MAX_ACTIVE_MEMORIES_PER_SCOPE = 100
# Whole-conversation extraction is deliberately review-gated. Keep its queue
# bounded too: otherwise inactive users can accumulate unlimited suggestions
# that are never eligible for recall but still inflate maintenance/API scans.
MAX_PENDING_REVIEW_MEMORIES_PER_SCOPE = 30
MAX_MEMORY_CONTEXT_TOKENS = 1_200
MAX_PROFILE_MEMORY_ROWS = 40
MEMORY_SEMANTIC_MIN = 0.55
MEMORY_RETRIEVAL_LIMIT = 4
MEMORY_IMPORTANCE_WEIGHT = 0.25
MEMORY_CONFIDENCE_WEIGHT = 0.25
MEMORY_INJECT_DEDUPE_COSINE = 0.88
MEMORY_CONSOLIDATE_SEMANTIC = 0.88
PROFILE_PREFERENCE_KEYS = frozenset(
    {"response_language", "response_style", "response_max_chars"}
)

SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?:密码|口令|验证码|动态码).{0,8}(?:是|为|[:：=])\s*\S{4,}"),
    re.compile(r"\b\d{15,18}[\dXx]\b"),
    re.compile(r"\b\d{13,19}\b"),
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?i)(?:home|work|mailing)\s+address\s*[:：=]"),
    re.compile(r"(?:家庭|住址|开户地址|详细地址)\s*[:：=]"),
    re.compile(
        r"(?i)(?:diagnos(?:is|ed)|medical history|prescription|病史|诊断|过敏史|"
        r"正在服用|心理疾病|精神疾病)"
    ),
]


@dataclass(frozen=True)
class MemoryCandidate:
    """A high-confidence memory inferred from user-authored evidence."""

    type: str
    key: str
    value: str
    content: str
    confidence: float
    importance: float
    source: str
    scope: str = "personal"
    expires_in_days: int | None = None
    evidence_message_ids: tuple[str, ...] = ()
    extractor_model: str | None = None
    extractor_version: str | None = None
