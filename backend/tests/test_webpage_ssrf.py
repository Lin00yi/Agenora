"""Security regression tests for URL document import."""
from __future__ import annotations

import socket

import pytest

from src.kb.parsers.webpage import _validate_external_url


def _addr(address: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/admin",
        "http://10.0.0.5/private",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "http://user:password@example.com/",
        "http://example.com:8080/",
    ],
)
async def test_external_url_guard_rejects_non_public_or_unsafe_urls(url, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: _addr("127.0.0.1"))
    with pytest.raises(ValueError):
        await _validate_external_url(url)


@pytest.mark.asyncio
async def test_external_url_guard_rejects_private_dns_answer(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: _addr("10.0.0.5"))
    with pytest.raises(ValueError, match="non-public"):
        await _validate_external_url("https://docs.example.com/path")


@pytest.mark.asyncio
async def test_external_url_guard_allows_public_https_target(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: _addr("8.8.8.8"))
    assert await _validate_external_url("https://docs.example.com/path") == "https://docs.example.com/path"


@pytest.mark.asyncio
async def test_external_url_guard_allows_clash_fake_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: _addr("198.18.0.225"))
    assert (
        await _validate_external_url("https://help.example.com/articles/1")
        == "https://help.example.com/articles/1"
    )
