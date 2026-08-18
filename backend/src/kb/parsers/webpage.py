"""URL fetcher + main-content extractor — httpx + trafilatura.

trafilatura is purpose-built for "give me the article text" extraction across
arbitrary news/blog/doc sites; it strips chrome, nav, ads, comments.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
import trafilatura

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 Agenora-KB/1.0"
)
_MAX_REDIRECTS = 3
_MAX_FETCH_BYTES = 10 * 1024 * 1024
# Clash / Surge fake-ip (RFC 2544). Local TUN proxies map public hostnames
# here; the range is not routed on the public Internet. Still reject
# loopback, RFC1918, link-local, and cloud metadata addresses.
_FAKE_IP_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),)


def _is_allowed_resolved_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_global:
        return True
    return any(ip in network for network in _FAKE_IP_NETWORKS)


async def _validate_external_url(url: str) -> str:
    """Allow only public HTTP(S) URLs before each outbound request.

    Document import runs inside the API container, so accepting an arbitrary
    URL would otherwise allow an authenticated caller to probe loopback,
    private Docker networks, and cloud metadata services.  We validate the
    initial target *and every redirect* and deliberately disable environment
    proxies in ``parse_url`` below.

    The hostname is resolved immediately before use.  A deployment that needs
    to fetch an intranet wiki should expose it through an authenticated public
    gateway rather than weakening this boundary for every tenant.
    """
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL") from exc

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL scheme must be http or https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must contain a hostname and no user credentials")
    # Non-standard ports are overwhelmingly used to reach internal services;
    # public websites normally use the scheme default.
    if port is not None and port not in {80, 443}:
        raise ValueError("URL port must be 80 or 443")

    try:
        resolved = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved") from exc

    addresses = {item[4][0].split("%", 1)[0] for item in resolved if item[4]}
    if not addresses:
        raise ValueError("URL hostname did not resolve to an address")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("URL hostname resolved to an invalid address") from exc
        # ``is_global`` excludes private, loopback, link-local, multicast,
        # unspecified, reserved, and documentation-only ranges for IPv4/IPv6.
        if not _is_allowed_resolved_ip(ip):
            raise ValueError("URL hostname resolves to a non-public address")
    return url


async def parse_url(url: str, *, timeout: float = 30.0) -> tuple[str, str]:
    """Fetch URL → extracted (title, text).

    Raises:
        httpx.HTTPError — network / non-2xx
        ValueError      — content extraction returned nothing
    """
    target = await _validate_external_url(url)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        for redirect_count in range(_MAX_REDIRECTS + 1):
            async with client.stream("GET", target) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect response has no Location header")
                    if redirect_count >= _MAX_REDIRECTS:
                        raise ValueError("URL exceeded redirect limit")
                    target = await _validate_external_url(str(response.url.join(location)))
                    continue

                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > _MAX_FETCH_BYTES:
                    raise ValueError("webpage is too large to import")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_FETCH_BYTES:
                        raise ValueError("webpage is too large to import")
                html = body.decode(response.encoding or "utf-8", errors="replace")
                break
        else:  # pragma: no cover - the loop either breaks or raises above
            raise ValueError("URL could not be fetched")

    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        output_format="txt",
        no_fallback=False,
    )
    if not extracted or not extracted.strip():
        raise ValueError(f"no readable content extracted from URL: {url}")

    title = url
    try:
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            title = meta.title
    except Exception:  # noqa: BLE001
        pass  # metadata is nice-to-have; URL is fine as fallback

    return title, extracted.strip()
