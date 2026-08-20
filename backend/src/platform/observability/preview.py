"""Helpers for truncating / redacting trace IO previews."""
from __future__ import annotations

import json
from typing import Any

_PREVIEW_MAX = 2000


def preview_text(value: Any, *, max_len: int = _PREVIEW_MAX, store_io: bool = True) -> str | None:
    """Serialize and truncate a value for DB / Langfuse preview fields."""
    if not store_io or value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def usage_from_sdk(usage: Any) -> dict[str, int] | None:
    """Normalize Anthropic / OpenAI usage objects into a plain dict."""
    if usage is None:
        return None
    in_t = getattr(usage, "input_tokens", None)
    out_t = getattr(usage, "output_tokens", None)
    if in_t is None:
        in_t = getattr(usage, "prompt_tokens", 0) or 0
    if out_t is None:
        out_t = getattr(usage, "completion_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return {
        "input_tokens": int(in_t or 0),
        "output_tokens": int(out_t or 0),
        "cache_read_tokens": int(cache_read),
        "cache_creation_tokens": int(cache_create),
    }
