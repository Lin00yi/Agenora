"""Normalize search tool hits into structured citation cards for the chat UI.

KB and web results use different score semantics, so they stay on separate
channels (`kb` | `web`) and are never mixed into one “相关度” list.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


Citation = dict[str, Any]

_URL_RE = re.compile(r"^https?://", re.I)
_BARE_HOST_PATH_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}/", re.I)


def citations_from_tool_raw(tool_name: str, raw: Any) -> list[Citation]:
    """Extract UI citations from a ToolResult.raw payload."""
    if not isinstance(raw, dict):
        return []
    results = raw.get("results")
    if not isinstance(results, list) or not results:
        return []

    if tool_name == "search_kb":
        kb_id = raw.get("kb_id")
        out: list[Citation] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename") or "").strip() or "(unknown)"
            score_raw = item.get("score")
            try:
                score = float(score_raw) if score_raw is not None else None
            except (TypeError, ValueError):
                score = None
            snippet = str(item.get("text_preview") or item.get("snippet") or "").strip()
            doc_id = item.get("doc_id")
            url = as_http_url(filename)
            out.append(
                {
                    "channel": "kb",
                    "title": filename,
                    "source": _hostname(url) if url else filename,
                    "score": score,
                    "url": url,
                    "snippet": snippet[:240] if snippet else None,
                    "kb_id": item.get("kb_id") or kb_id,
                    "doc_id": str(doc_id) if doc_id else None,
                }
            )
        return out

    if tool_name == "web_search":
        out = []
        for item in results:
            if not isinstance(item, dict):
                continue
            raw_url = str(item.get("url") or "").strip()
            url = as_http_url(raw_url) or (raw_url or None)
            title = str(item.get("title") or "").strip() or url or "(untitled)"
            body = str(item.get("body") or item.get("snippet") or "").strip()
            out.append(
                {
                    "channel": "web",
                    "title": title[:160],
                    "source": _hostname(url or "") or url or title,
                    "score": None,
                    "url": url,
                    "snippet": body[:240] if body else None,
                    "kb_id": None,
                    "doc_id": None,
                }
            )
        return out

    return []


def as_http_url(value: str) -> str | None:
    """Normalize filename/source strings that are actually web URLs."""
    v = (value or "").strip()
    if not v:
        return None
    if _URL_RE.match(v):
        return v
    if _BARE_HOST_PATH_RE.match(v):
        return f"https://{v}"
    return None


def merge_citations(*groups: list[Citation] | None) -> list[Citation]:
    """Dedupe citations across tool calls; keep highest KB score per source."""
    merged: list[Citation] = []
    index: dict[str, int] = {}
    for group in groups:
        if not group:
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            channel = str(item.get("channel") or "").strip()
            if channel not in {"kb", "web"}:
                continue
            key = _citation_key(item)
            if key in index:
                existing = merged[index[key]]
                if channel == "kb":
                    prev = existing.get("score")
                    nxt = item.get("score")
                    try:
                        if nxt is not None and (prev is None or float(nxt) > float(prev)):
                            merged[index[key]] = {**existing, **item, "score": float(nxt)}
                    except (TypeError, ValueError):
                        pass
                continue
            index[key] = len(merged)
            merged.append(dict(item))
    return merged


def _citation_key(item: Citation) -> str:
    channel = str(item.get("channel") or "")
    if channel == "web":
        url = str(item.get("url") or "").strip().lower()
        return f"web|{url or item.get('title') or ''}"
    # Prefer URL identity when KB docs were ingested from the web.
    url = str(item.get("url") or "").strip().lower()
    if url:
        return f"kb-url|{url}"
    kb_id = str(item.get("kb_id") or "")
    doc_id = str(item.get("doc_id") or "")
    source = str(item.get("source") or item.get("title") or "")
    return f"kb|{kb_id}|{doc_id}|{source}"


def _hostname(url: str) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host
