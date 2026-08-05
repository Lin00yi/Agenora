"""Token counting for context budgeting.

Uses tiktoken when available. Encoding is selected from the active model when
known; otherwise ``cl100k_base`` is a stable proxy for OpenAI-compatible,
DeepSeek, and Claude budgeting. A tiny pad absorbs cross-tokenizer drift
without returning to the old CJK heuristic's heavy overestimate.

Call sites that already know the model should wrap work in
``token_model_scope(model)`` so nested ``estimate_tokens`` calls pick the
right encoding without threading the model through every helper.
"""
from __future__ import annotations

import contextvars
import logging
import math
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger(__name__)

_token_model: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "knowflow_token_model", default=None
)
_encoding_cache: dict[str, object] = {}
_tiktoken_failed = False

# Slight pad so provider tokenizers that diverge from tiktoken still fit.
# Far smaller than the former CJK heuristic overestimate.
TOKEN_COUNT_PAD = 1.03


def heuristic_estimate_tokens(text: str) -> int:
    """Fallback multilingual estimate used when tiktoken is unavailable."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = max(len(text) - cjk, 0)
    return max(1, int(cjk * 1.2 + other / 3.2))


def encoding_name_for_model(model: str | None) -> str:
    """Pick a tiktoken encoding name for the model family."""
    if not model:
        return "cl100k_base"
    normalized = model.lower()
    if normalized.startswith("gpt-4o") or normalized.startswith(
        ("o1", "o3", "o4", "gpt-5")
    ):
        return "o200k_base"
    if "gpt-4o" in normalized or normalized.endswith("-4o") or "-4o-" in normalized:
        return "o200k_base"
    if normalized.startswith(("gpt-4", "gpt-3.5", "text-embedding-3", "text-embedding-ada")):
        return "cl100k_base"
    # DeepSeek / Claude / BYOK: cl100k_base is a practical budgeting proxy.
    return "cl100k_base"


def current_token_model() -> str | None:
    return _token_model.get()


@contextmanager
def token_model_scope(model: str | None) -> Iterator[None]:
    """Bind the model used by nested ``estimate_tokens`` / truncate helpers."""
    token = _token_model.set(model)
    try:
        yield
    finally:
        _token_model.reset(token)


def _get_encoding(name: str):
    global _tiktoken_failed
    if _tiktoken_failed:
        return None
    cached = _encoding_cache.get(name)
    if cached is not None:
        return cached
    try:
        import tiktoken

        encoding = tiktoken.get_encoding(name)
    except Exception as exc:  # noqa: BLE001 - budgeting must stay available
        log.warning("tiktoken unavailable (%s); falling back to heuristic token estimates", exc)
        _tiktoken_failed = True
        return None
    _encoding_cache[name] = encoding
    return encoding


def count_tokens(text: str, *, model: str | None = None) -> int:
    """Return a budget-safe token count for ``text``."""
    if not text:
        return 0
    effective_model = model if model is not None else _token_model.get()
    encoding = _get_encoding(encoding_name_for_model(effective_model))
    if encoding is None:
        return heuristic_estimate_tokens(text)
    try:
        raw = len(encoding.encode(text))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return heuristic_estimate_tokens(text)
    if raw <= 0:
        return 0
    return max(1, int(math.ceil(raw * TOKEN_COUNT_PAD)))


def truncate_to_token_budget(
    text: str,
    token_budget: int,
    *,
    suffix: str = "…[已截断]",
    model: str | None = None,
) -> str:
    """Keep a prefix of ``text`` that fits ``token_budget`` tokens."""
    if token_budget <= 0:
        return ""
    if not text:
        return ""
    if count_tokens(text, model=model) <= token_budget:
        return text

    effective_model = model if model is not None else _token_model.get()
    encoding = _get_encoding(encoding_name_for_model(effective_model))
    if encoding is not None:
        try:
            ids = list(encoding.encode(text))  # type: ignore[attr-defined]
            if int(math.ceil(len(ids) * TOKEN_COUNT_PAD)) <= token_budget:
                return text
            # Binary-search the kept prefix length. Re-encode the candidate
            # because decode(ids[:n]) + suffix can tokenize differently than
            # ids[:n] + encode(suffix).
            low, high = 0, len(ids)
            best = ""
            while low < high:
                middle = (low + high + 1) // 2
                candidate = encoding.decode(ids[:middle]) + suffix  # type: ignore[attr-defined]
                if count_tokens(candidate, model=model) <= token_budget:
                    low = middle
                    best = candidate
                else:
                    high = middle - 1
            return best
        except Exception:  # noqa: BLE001 - fall through to char binary search
            pass

    low, high = 0, len(text)
    best = ""
    while low < high:
        middle = (low + high + 1) // 2
        candidate = text[:middle].rstrip() + suffix
        if count_tokens(candidate, model=model) <= token_budget:
            low = middle
            best = candidate
        else:
            high = middle - 1
    return best
