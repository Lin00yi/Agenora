"""HTTP client for LightRAG Server (not embedded Core).

Isolation: each Agenora KB maps to a LightRAG workspace via the
``LIGHTRAG-WORKSPACE`` request header (sanitized ``kb_id``).

Auth: optional ``X-API-Key`` from settings.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from src.settings import get_settings

log = structlog.get_logger()

_WORKSPACE_RE = re.compile(r"[^a-zA-Z0-9_]+")

# Process-wide client — avoids TLS/handshake cost on every KG query.
_http_client: httpx.AsyncClient | None = None


def workspace_for_kb(kb_id: str) -> str:
    """Sanitize KB id for LightRAG workspace header (alphanumeric + underscore)."""
    cleaned = _WORKSPACE_RE.sub("_", (kb_id or "").strip())
    return cleaned or "default"


def file_source_for_doc(kb_id: str, doc_id: str, filename: str = "") -> str:
    """Stable LightRAG file_source so deletes can be correlated."""
    safe_name = (filename or "doc").replace("/", "_").replace("\\", "_")[:180]
    return f"agenora/{kb_id}/{doc_id}/{safe_name}"


def _get_http_client(timeout_s: float) -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=timeout_s)
    return _http_client


async def aclose_lightrag_http() -> None:
    """Optional cleanup on app shutdown."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


class LightRAGClient:
    """Thin async wrapper around LightRAG Server REST API."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.lightrag_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.lightrag_api_key
        self.timeout_s = (
            timeout_s if timeout_s is not None else float(settings.lightrag_timeout_s)
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _headers(self, kb_id: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "LIGHTRAG-WORKSPACE": workspace_for_kb(kb_id),
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _client(self) -> httpx.AsyncClient:
        return _get_http_client(self.timeout_s)

    async def health(self) -> dict[str, Any]:
        resp = await self._client().get(
            f"{self.base_url}/health",
            headers=self._headers("health"),
            timeout=min(10.0, self.timeout_s),
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {"status": "ok"}

    async def insert_text(
        self,
        *,
        kb_id: str,
        text: str,
        file_source: str,
    ) -> dict[str, Any]:
        payload = {"text": text, "file_source": file_source}
        resp = await self._client().post(
            f"{self.base_url}/documents/text",
            headers=self._headers(kb_id),
            json=payload,
            timeout=self.timeout_s,
        )
        if resp.status_code >= 400:
            detail = (resp.text or "")[:800]
            raise RuntimeError(
                f"LightRAG insert failed ({resp.status_code}): {detail}"
            )
        return resp.json()

    async def query_context(
        self,
        *,
        kb_id: str,
        query: str,
        mode: str | None = None,
        top_k: int | None = None,
    ) -> str:
        settings = get_settings()
        q = (query or "").strip()
        if len(q) < 3:
            # LightRAG rejects queries shorter than 3 chars.
            q = (q + "   ")[:3] if q else "   "
        payload: dict[str, Any] = {
            "query": q,
            "mode": mode or settings.lightrag_query_mode,
            "only_need_context": True,
            "enable_rerank": False,
        }
        if top_k is not None:
            payload["top_k"] = max(1, min(int(top_k), 60))
        resp = await self._client().post(
            f"{self.base_url}/query",
            headers=self._headers(kb_id),
            json=payload,
            timeout=self.timeout_s,
        )
        if resp.status_code >= 400:
            detail = (resp.text or "")[:800]
            raise RuntimeError(
                f"LightRAG query failed ({resp.status_code}): {detail}"
            )
        data = resp.json() if resp.content else {}
        # Response shapes vary by version: string, or {response|data|content|context}.
        if isinstance(data, str):
            return data
        for key in ("response", "data", "content", "context", "result"):
            val = data.get(key) if isinstance(data, dict) else None
            if isinstance(val, str) and val.strip():
                return val
        if isinstance(data, dict) and data:
            return str(data)
        return ""

    async def track_status(self, *, kb_id: str, track_id: str) -> dict[str, Any]:
        resp = await self._client().get(
            f"{self.base_url}/documents/track_status/{track_id}",
            headers=self._headers(kb_id),
            timeout=min(30.0, self.timeout_s),
        )
        if resp.status_code >= 400:
            detail = (resp.text or "")[:500]
            raise RuntimeError(
                f"LightRAG track_status failed ({resp.status_code}): {detail}"
            )
        return resp.json() if resp.content else {}

    async def delete_documents(self, *, kb_id: str, doc_ids: list[str]) -> dict[str, Any]:
        ids = [d.strip() for d in doc_ids if d and d.strip()]
        if not ids:
            return {"status": "skipped", "message": "no doc ids"}
        resp = await self._client().request(
            "DELETE",
            f"{self.base_url}/documents/delete_document",
            headers=self._headers(kb_id),
            json={"doc_ids": ids, "delete_file": False, "delete_llm_cache": False},
            timeout=self.timeout_s,
        )
        if resp.status_code >= 400:
            detail = (resp.text or "")[:800]
            raise RuntimeError(
                f"LightRAG delete failed ({resp.status_code}): {detail}"
            )
        return resp.json() if resp.content else {"status": "success"}

    async def resolve_doc_ids_from_track(
        self, *, kb_id: str, track_id: str
    ) -> list[str]:
        """Best-effort extract LightRAG document ids from a track_status payload."""
        if not track_id:
            return []
        try:
            data = await self.track_status(kb_id=kb_id, track_id=track_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("lightrag_track_resolve_failed", track_id=track_id, error=str(exc))
            return []
        docs = data.get("documents") if isinstance(data, dict) else None
        if not isinstance(docs, list):
            return []
        out: list[str] = []
        for item in docs:
            if isinstance(item, dict):
                did = item.get("id") or item.get("doc_id")
                if did:
                    out.append(str(did))
        return out


def get_lightrag_client() -> LightRAGClient:
    return LightRAGClient()
