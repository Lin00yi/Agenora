"""Prompt-injection detection helpers for user input and retrieved RAG text.

The guard is intentionally deterministic and conservative. It does not try to
"understand" every attack; it tags high-signal patterns so orchestration code
can isolate untrusted content, disable retrieval, or strengthen the system
prompt before the model sees the text.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class PromptInjectionAssessment:
    level: RiskLevel
    reasons: list[str]
    normalized_text: str


_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_WHITESPACE = re.compile(r"\s+")

_HIGH_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "prompt_leak_attempt",
        re.compile(
            r"(system|developer)\s+(prompt|message|instruction)|"
            r"(reveal|show|print|dump|leak).{0,30}(prompt|instruction|system message)|"
            r"(输出|显示|打印|泄露|透露).{0,12}(系统提示词|开发者消息|system prompt|prompt)",
            re.IGNORECASE,
        ),
    ),
    (
        "secret_exfiltration_attempt",
        re.compile(
            r"(reveal|show|print|dump|leak|exfiltrate|tell me).{0,30}"
            r"(api[_ -]?key|token|jwt|secret|password|private key|credential)|"
            r"(输出|显示|打印|泄露|透露|告诉我).{0,18}"
            r"(api[_ -]?key|token|jwt|secret|password|private key|credential|密钥|令牌|凭据|密码|私钥)",
            re.IGNORECASE,
        ),
    ),
)

_MEDIUM_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"(ignore|forget|disregard|bypass|override).{0,40}"
            r"(previous|above|system|developer|instruction|rules)|"
            r"(忽略|忘记|无视|绕过|覆盖).{0,20}(之前|以上|系统|开发者|规则|指令)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_or_policy_change",
        re.compile(
            r"(you are now|act as|pretend to be|jailbreak|dan mode)|"
            r"(你现在是|扮演|假装|越狱|开发者模式)",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_or_url_coercion",
        re.compile(
            r"(call|invoke|use).{0,20}(tool|function|web_search|browser)|"
            r"(访问|打开|调用|使用).{0,18}(工具|函数|链接|网址|url|web_search)",
            re.IGNORECASE,
        ),
    ),
)


def normalize_for_prompt_guard(text: str) -> str:
    """Normalize obvious obfuscation before applying prompt-injection rules."""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = _ZERO_WIDTH.sub("", normalized)
    normalized = _WHITESPACE.sub(" ", normalized)
    return normalized.strip()


def assess_prompt_injection(text: str) -> PromptInjectionAssessment:
    """Return a risk label and machine-readable reasons for a text block."""
    normalized = normalize_for_prompt_guard(text)
    if not normalized:
        return PromptInjectionAssessment("low", [], "")

    reasons: list[str] = []
    for reason, pattern in _HIGH_RISK_PATTERNS:
        if pattern.search(normalized):
            reasons.append(reason)
    for reason, pattern in _MEDIUM_RISK_PATTERNS:
        if pattern.search(normalized):
            reasons.append(reason)

    if any(reason in {"prompt_leak_attempt", "secret_exfiltration_attempt"} for reason in reasons):
        level: RiskLevel = "high"
    elif reasons:
        level = "medium"
    else:
        level = "low"
    return PromptInjectionAssessment(level, reasons, normalized)


def filter_untrusted_rag_text(text: str) -> tuple[str, int, list[str]]:
    """Remove suspicious RAG blocks before they become model context.

    KB search results are formatted as chunk blocks separated by ``---``. Each
    block is untrusted user-controlled document data, so medium/high-risk blocks
    are replaced with a neutral marker instead of being injected into
    ``<kb_context>``.
    """
    if not text:
        return "", 0, []

    blocks = text.split("\n\n---\n\n")
    safe_blocks: list[str] = []
    suspicious_count = 0
    reasons: list[str] = []
    for block in blocks:
        assessment = assess_prompt_injection(block)
        if assessment.level in {"medium", "high"}:
            suspicious_count += 1
            reasons.extend(assessment.reasons)
            safe_blocks.append(
                "[suspicious KB chunk filtered: possible prompt-injection instructions]"
            )
            continue
        safe_blocks.append(block)

    deduped_reasons = sorted(set(reasons))
    return "\n\n---\n\n".join(safe_blocks), suspicious_count, deduped_reasons
