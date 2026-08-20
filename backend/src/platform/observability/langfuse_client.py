"""Lazy Langfuse client bootstrap (no-op without keys / package)."""
from __future__ import annotations

import re
from typing import Any

import structlog

from src.settings import get_settings

log = structlog.get_logger()

_client: Any | None = None
_init_attempted = False
_warned_missing_keys = False
_warned_import = False

# Langfuse environment: lowercase alnum + hyphen/underscore, <=40, not "langfuse*".
_ENV_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_ENV_ALIASES = {
    "prod": "production",
    "production": "production",
    "dev": "development",
    "development": "development",
    "stage": "staging",
    "staging": "staging",
    "stg": "staging",
    "test": "test",
    "testing": "test",
    "local": "local",
}


def resolve_langfuse_environment() -> str:
    """Map APP_ENV / LANGFUSE_TRACING_ENVIRONMENT to a Langfuse environment slug.

    Prefer explicit LANGFUSE_TRACING_ENVIRONMENT; otherwise derive from app_env.
    Falls back to ``development`` when the value is invalid for Langfuse.
    """
    s = get_settings()
    raw = (s.langfuse_tracing_environment or s.app_env or "development").strip().lower()
    env = _ENV_ALIASES.get(raw, raw)
    if env.startswith("langfuse") or not _ENV_RE.match(env):
        log.warning(
            "langfuse_environment_invalid",
            value=raw,
            fallback="development",
        )
        return "development"
    return env


def build_langfuse_tags(
    *,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Stable filter tags for Langfuse Trace Tags column / UI filters."""
    meta = metadata or {}
    tags: list[str] = [name] if name else ["chat"]
    if meta.get("kb_id"):
        tags.append("kb")
    else:
        tags.append("general")
    model = meta.get("model")
    if isinstance(model, str) and model.strip():
        tag = f"model:{model.strip()}"
        if len(tag) <= 200:
            tags.append(tag)
    # Dedupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def stamp_langfuse_trace_attrs(
    lf_obs: Any,
    *,
    trace_name: str,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    environment: str | None = None,
) -> None:
    """Stamp first-class Langfuse trace fields onto an observation's OTel span.

    SDK v3+ stores Trace Name / Tags / User / Session as span attributes that
    must be present on *each* observation for UI columns and aggregations.
    ``update_trace`` is gone; ``propagate_attributes`` needs an active OTel
    context which we cannot keep across ``asyncio.create_task``.
    """
    otel = getattr(lf_obs, "_otel_span", None)
    if otel is None:
        return
    try:
        if not otel.is_recording():
            return
    except Exception:  # noqa: BLE001
        return

    try:
        from langfuse._client.attributes import LangfuseOtelSpanAttributes
    except ImportError:
        return

    attrs: dict[str, Any] = {}
    if trace_name:
        attrs[LangfuseOtelSpanAttributes.TRACE_NAME] = str(trace_name)[:200]
    if user_id:
        attrs[LangfuseOtelSpanAttributes.TRACE_USER_ID] = str(user_id)[:200]
    if session_id:
        attrs[LangfuseOtelSpanAttributes.TRACE_SESSION_ID] = str(session_id)[:200]
    if tags:
        attrs[LangfuseOtelSpanAttributes.TRACE_TAGS] = [
            str(t)[:200] for t in tags if t
        ]
    env = environment or resolve_langfuse_environment()
    if env:
        attrs[LangfuseOtelSpanAttributes.ENVIRONMENT] = env

    try:
        if attrs:
            otel.set_attributes(attrs)
        # Trace metadata is flattened as langfuse.trace.metadata.<key>
        if metadata:
            for key, value in metadata.items():
                if value is None:
                    continue
                k = str(key)
                if not k.isascii():
                    continue
                v = value if isinstance(value, str) else str(value)
                if len(v) > 200:
                    v = v[:199] + "…"
                otel.set_attribute(
                    f"{LangfuseOtelSpanAttributes.TRACE_METADATA}.{k}", v
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("langfuse_stamp_attrs_failed", error=str(exc))


def langfuse_configured() -> bool:
    """True when Langfuse export should be attempted."""
    s = get_settings()
    if not s.langfuse_enabled:
        return False
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return False
    return True


def get_langfuse() -> Any | None:
    """Return a Langfuse client, or None when disabled / unavailable."""
    global _client, _init_attempted, _warned_missing_keys, _warned_import

    s = get_settings()
    if not s.langfuse_enabled:
        return None

    if not (s.langfuse_public_key and s.langfuse_secret_key):
        if not _warned_missing_keys:
            log.warning(
                "langfuse_disabled_missing_keys",
                hint="Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY, or LANGFUSE_ENABLED=false",
            )
            _warned_missing_keys = True
        return None

    if _client is not None:
        return _client
    if _init_attempted:
        return None
    _init_attempted = True

    try:
        from langfuse import Langfuse
    except ImportError:
        if not _warned_import:
            log.warning(
                "langfuse_not_installed",
                hint="pip install langfuse (or reinstall backend deps)",
            )
            _warned_import = True
        return None

    try:
        environment = resolve_langfuse_environment()
        _client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host or "https://cloud.langfuse.com",
            sample_rate=float(s.langfuse_sample_rate),
            environment=environment,
        )
        log.info(
            "langfuse_enabled",
            host=s.langfuse_host,
            environment=environment,
        )
        return _client
    except Exception as exc:  # noqa: BLE001
        log.warning("langfuse_init_failed", error=str(exc))
        return None


def reset_langfuse_for_tests() -> None:
    """Clear cached client (unit tests only)."""
    global _client, _init_attempted, _warned_missing_keys, _warned_import
    _client = None
    _init_attempted = False
    _warned_missing_keys = False
    _warned_import = False
