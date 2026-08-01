"""Search provider adapters used by WebSearchTool."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx

from src.settings import get_settings


@dataclass
class SearchResult:
    title: str
    url: str
    body: str


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]: ...


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        def _run() -> list[dict]:
            from ddgs import DDGS

            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        results = await asyncio.to_thread(_run)
        return [
            SearchResult(
                title=(r.get("title") or "").strip(),
                url=(r.get("href") or r.get("url") or "").strip(),
                body=(r.get("body") or "").strip(),
            )
            for r in results
        ]


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("BRAVE_SEARCH_API_KEY is required for WEB_SEARCH_PROVIDER=brave")
        self.api_key = api_key

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
                params={"q": query, "count": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        rows = (data.get("web") or {}).get("results") or []
        return [
            SearchResult(
                title=(r.get("title") or "").strip(),
                url=(r.get("url") or "").strip(),
                body=(r.get("description") or "").strip(),
            )
            for r in rows[:max_results]
        ]


class BingSearchProvider:
    name = "bing"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("BING_SEARCH_API_KEY is required for WEB_SEARCH_PROVIDER=bing")
        self.api_key = api_key

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.bing.microsoft.com/v7.0/search",
                headers={"Ocp-Apim-Subscription-Key": self.api_key},
                params={"q": query, "count": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        rows = (data.get("webPages") or {}).get("value") or []
        return [
            SearchResult(
                title=(r.get("name") or "").strip(),
                url=(r.get("url") or "").strip(),
                body=(r.get("snippet") or "").strip(),
            )
            for r in rows[:max_results]
        ]


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY is required for WEB_SEARCH_PROVIDER=tavily")
        self.api_key = api_key

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        rows = data.get("results") or []
        return [
            SearchResult(
                title=(r.get("title") or "").strip(),
                url=(r.get("url") or "").strip(),
                body=(r.get("content") or "").strip(),
            )
            for r in rows[:max_results]
        ]


def get_search_provider() -> SearchProvider:
    settings = get_settings()
    provider = (settings.web_search_provider or "duckduckgo").strip().lower()
    if provider in {"duckduckgo", "ddg"}:
        return DuckDuckGoSearchProvider()
    if provider == "brave":
        return BraveSearchProvider(settings.brave_search_api_key)
    if provider == "bing":
        return BingSearchProvider(settings.bing_search_api_key)
    if provider == "tavily":
        return TavilySearchProvider(settings.tavily_api_key)
    raise ValueError(
        "Unknown WEB_SEARCH_PROVIDER="
        f"'{settings.web_search_provider}'. Supported: duckduckgo, brave, bing, tavily."
    )
