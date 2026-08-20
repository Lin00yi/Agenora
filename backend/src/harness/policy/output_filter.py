"""Output filters for PII, secret, and prompt-leak redaction."""
from __future__ import annotations

import re

PHONE = re.compile(r"\b1[3-9]\d{9}\b")
ID_CARD = re.compile(r"\b\d{17}[\dXx]\b")
OPENAI_STYLE_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
PROMPT_LEAK_LINE = re.compile(
    r"(?im)^\s*(system|developer)\s+(prompt|message|instruction)\s*[:：].*$"
)
INTERNAL_COLLECTION = re.compile(r"\b(kb_[a-f0-9]{8,}|collection_[A-Za-z0-9_-]+)\b")


def redact_pii(text: str) -> str:
    """Backward-compatible PII redactor used by existing tests and callers."""
    redacted = PHONE.sub("[phone redacted]", text or "")
    redacted = ID_CARD.sub("[id card redacted]", redacted)
    return redacted


def redact_sensitive_output(text: str) -> str:
    """Redact secrets and prompt-leak shaped output before streaming to users."""
    redacted = redact_pii(text)
    redacted = PRIVATE_KEY_BLOCK.sub("[private key redacted]", redacted)
    redacted = OPENAI_STYLE_KEY.sub("[api key redacted]", redacted)
    redacted = JWT.sub("[jwt redacted]", redacted)
    redacted = PROMPT_LEAK_LINE.sub("[system/developer prompt redacted]", redacted)
    redacted = INTERNAL_COLLECTION.sub("[internal collection redacted]", redacted)
    return redacted
