"""Prompt-injection detection helpers for user input and retrieved RAG text.

The guard is intentionally deterministic and conservative. It does not try to
"understand" every attack; it tags high-signal patterns so orchestration code
can isolate untrusted content, disable retrieval, or strengthen the system
prompt before the model sees the text.

Rules load from ``backend/config/prompt_injection_rules.yaml`` when present,
with the built-in patterns below as a hard fallback.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]

log = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "prompt_injection_rules.yaml"

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_WHITESPACE = re.compile(r"\s+")

# Built-in fallback — kept in sync with config/prompt_injection_rules.yaml.
_FALLBACK_HIGH: tuple[tuple[str, str], ...] = (
    (
        "prompt_leak_attempt",
        (
            r"(system|developer)\s+(prompt|message|instruction)|"
            r"(reveal|show|print|dump|leak).{0,30}(prompt|instruction|system message)|"
            r"(输出|显示|打印|泄露|透露).{0,12}(系统提示词|开发者消息|system prompt|prompt)"
        ),
    ),
    (
        "secret_exfiltration_attempt",
        (
            r"(reveal|show|print|dump|leak|exfiltrate|tell me).{0,30}"
            r"(api[_ -]?key|token|jwt|secret|password|private key|credential)|"
            r"(输出|显示|打印|泄露|透露|告诉我).{0,18}"
            r"(api[_ -]?key|token|jwt|secret|password|private key|credential|密钥|令牌|凭据|密码|私钥)"
        ),
    ),
)

_FALLBACK_MEDIUM: tuple[tuple[str, str], ...] = (
    (
        "instruction_override",
        (
            r"(ignore|forget|disregard|bypass|override).{0,40}"
            r"(previous|above|system|developer|instruction|rules)|"
            r"(忽略|忘记|无视|绕过|覆盖).{0,20}(之前|以上|系统|开发者|规则|指令)"
        ),
    ),
    (
        "role_or_policy_change",
        (
            r"(you are now|act as|pretend to be|jailbreak|dan mode)|"
            r"(你现在是|扮演|假装|越狱|开发者模式)"
        ),
    ),
    (
        "tool_or_url_coercion",
        (
            r"(call|invoke|use).{0,20}(tool|function|web_search|browser)|"
            r"(访问|打开|调用|使用).{0,18}(工具|函数|链接|网址|url|web_search)"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class PromptInjectionAssessment:
    level: RiskLevel
    reasons: list[str]
    normalized_text: str


def _compile_rules(
    entries: list[tuple[str, str]],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for reason, pattern in entries:
        compiled.append((reason, re.compile(pattern, re.IGNORECASE)))
    return tuple(compiled)


def _entries_from_yaml(section: list[dict] | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in section or []:
        reason = str(item.get("id") or "").strip()
        raw_pattern = item.get("pattern")
        if isinstance(raw_pattern, list):
            parts = [str(p).strip() for p in raw_pattern if str(p).strip()]
            pattern = "|".join(parts)
        else:
            pattern = str(raw_pattern or "").strip()
        if reason and pattern:
            out.append((reason, pattern))
    return out


@lru_cache(maxsize=1)
def _load_pattern_groups() -> tuple[
    tuple[tuple[str, re.Pattern[str]], ...],
    tuple[tuple[str, re.Pattern[str]], ...],
]:
    high_entries = list(_FALLBACK_HIGH)
    medium_entries = list(_FALLBACK_MEDIUM)
    if _RULES_PATH.is_file():
        try:
            import yaml  # type: ignore[import-untyped]

            raw = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8")) or {}
            high_yaml = _entries_from_yaml(raw.get("high_risk"))
            medium_yaml = _entries_from_yaml(raw.get("medium_risk"))
            if high_yaml:
                high_entries = high_yaml
            if medium_yaml:
                medium_entries = medium_yaml
            log.info(
                "prompt_injection_rules_loaded path=%s high=%s medium=%s",
                _RULES_PATH,
                len(high_entries),
                len(medium_entries),
            )
        except Exception as exc:  # noqa: BLE001 — keep serving with builtins
            log.warning(
                "prompt_injection_rules_load_failed path=%s err=%s; using builtins",
                _RULES_PATH,
                exc,
            )
    return _compile_rules(high_entries), _compile_rules(medium_entries)


def reload_prompt_injection_rules() -> None:
    """Clear the cached rule set (tests / hot-reload after editing YAML)."""
    _load_pattern_groups.cache_clear()


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

    high_patterns, medium_patterns = _load_pattern_groups()
    reasons: list[str] = []
    for reason, pattern in high_patterns:
        if pattern.search(normalized):
            reasons.append(reason)
    for reason, pattern in medium_patterns:
        if pattern.search(normalized):
            reasons.append(reason)

    if any(reason in {"prompt_leak_attempt", "secret_exfiltration_attempt"} for reason in reasons):
        level: RiskLevel = "high"
    elif reasons:
        level = "medium"
    else:
        level = "low"
    return PromptInjectionAssessment(level, reasons, normalized)


def filter_untrusted_rag_text(
    text: str,
    *,
    preview_chars: int = 240,
) -> tuple[str, int, list[str], list[dict[str, Any]]]:
    """Remove suspicious RAG blocks before they become model context.

    KB search results are formatted as chunk blocks separated by ``---``. Each
    block is untrusted user-controlled document data, so medium/high-risk blocks
    are replaced with a neutral marker instead of being injected as
    ``retrieved_evidence``.

    Returns ``(filtered_text, suspicious_count, reasons, filtered_details)``.
    ``filtered_details`` is audit-only metadata (never intended for the model).
    """
    if not text:
        return "", 0, [], []

    blocks = text.split("\n\n---\n\n")
    safe_blocks: list[str] = []
    suspicious_count = 0
    reasons: list[str] = []
    filtered_details: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        assessment = assess_prompt_injection(block)
        if assessment.level in {"medium", "high"}:
            suspicious_count += 1
            reasons.extend(assessment.reasons)
            preview = " ".join((block or "").split())
            if len(preview) > preview_chars:
                preview = preview[: preview_chars - 1] + "…"
            filtered_details.append(
                {
                    "block_index": index,
                    "level": assessment.level,
                    "reasons": list(assessment.reasons),
                    "preview": preview,
                }
            )
            safe_blocks.append(
                "[suspicious KB chunk filtered: possible prompt-injection instructions]"
            )
            continue
        safe_blocks.append(block)

    deduped_reasons = sorted(set(reasons))
    return "\n\n---\n\n".join(safe_blocks), suspicious_count, deduped_reasons, filtered_details


def enrich_filtered_rag_chunks(
    details: list[dict[str, Any]],
    *,
    channel: str,
    query: str | None = None,
    tool_raw: Any = None,
) -> list[dict[str, Any]]:
    """Attach retrieval metadata to filter audit rows (doc_id / score / …).

    ``search_kb`` ``raw.results`` is ordered the same as ``---`` text blocks, so
    ``block_index`` lines up with structured hit metadata when present.
    """
    structured: list[dict[str, Any]] = []
    kb_id: str | None = None
    if isinstance(tool_raw, dict):
        kb_id = tool_raw.get("kb_id") if isinstance(tool_raw.get("kb_id"), str) else None
        raw_results = tool_raw.get("results") or []
        if isinstance(raw_results, list):
            structured = [item for item in raw_results if isinstance(item, dict)]

    enriched: list[dict[str, Any]] = []
    for detail in details:
        row = {
            "channel": channel,
            "query": query,
            "kb_id": kb_id,
            "block_index": detail.get("block_index"),
            "level": detail.get("level"),
            "reasons": list(detail.get("reasons") or []),
            "preview": detail.get("preview") or "",
            "doc_id": None,
            "filename": None,
            "score": None,
        }
        idx = detail.get("block_index")
        if isinstance(idx, int) and 0 <= idx < len(structured):
            hit = structured[idx]
            row["doc_id"] = hit.get("doc_id")
            row["filename"] = hit.get("filename")
            try:
                row["score"] = float(hit.get("score")) if hit.get("score") is not None else None
            except (TypeError, ValueError):
                row["score"] = None
            # Prefer the structured preview when available (cleaner than header+text).
            if hit.get("text_preview"):
                row["preview"] = str(hit.get("text_preview"))[:240]
        enriched.append(row)
    return enriched
