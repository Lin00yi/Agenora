"""Versioned, administrator-owned MCP catalog persistence and publication."""
from __future__ import annotations

import json
import ipaddress
import hashlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.persistence.database import Base
from src.platform.security.crypto import decrypt, encrypt
from src.settings import get_settings

from .catalog import McpCatalog, McpServerSpec, _catalog_from_json
from .policies import supports_high_risk_policy

_CONFIG_ID = "platform"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class McpCatalogConfig(Base):
    """One platform catalog with separate draft and published snapshots."""

    __tablename__ = "mcp_catalog_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_CONFIG_ID)
    draft_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    draft_secrets_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_secrets_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class McpCatalogAudit(Base):
    """Metadata-only trace of catalog changes; never contains secret values."""

    __tablename__ = "mcp_catalog_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


class McpPluginSetRelease(Base):
    """Immutable, replayable PluginSet release used by durable runs.

    ``McpCatalogConfig`` is the mutable draft/current pointer. A release is
    never edited, so a paused approval can resolve exactly the MCP adapters
    that were active when its graph was compiled, including after a restart.
    """

    __tablename__ = "mcp_plugin_set_releases"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_json: Mapped[str] = mapped_column(Text, nullable=False)
    secrets_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _decrypt_secrets(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    value = _json_object(decrypt(raw))
    return {str(key): item for key, item in value.items() if isinstance(item, str) and item}


def _catalog_payload(catalog: McpCatalog) -> dict[str, Any]:
    return {
        "servers": [server.model_dump(mode="json") for server in catalog.servers.values()],
        "capabilities": [binding.model_dump(mode="json") for binding in catalog.capabilities.values()],
        "contracts": [
            contract.model_dump(mode="json") for contract in (catalog.contracts or {}).values()
        ],
        "plugins": [
            plugin.model_dump(mode="json") for plugin in (catalog.plugins or {}).values()
        ],
    }


def parse_catalog_payload(value: dict[str, Any]) -> McpCatalog:
    """Validate a reviewable catalog payload using the runtime schema."""
    catalog = _catalog_from_json(json.dumps(value, ensure_ascii=False))
    _validate_admin_catalog(catalog)
    return catalog


def _validate_admin_server(server: McpServerSpec) -> None:
    """Validate the Web-managed transport boundary.

    HTTP plugins are platform-safe after egress checks. STDIO is intentionally
    available only to a developer's local instance, where it follows Codex's
    command/args/env/cwd model; production deployments must package it through
    reviewed infrastructure instead of turning the admin page into RCE.
    """
    local_dev = get_settings().app_env.strip().lower() in {"dev", "development", "test"}
    if server.transport == "stdio":
        if not local_dev:
            raise ValueError(
                "stdio MCP is available only in local development; production stdio plugins are deployment-managed"
            )
        if server.endpoint or server.headers or server.secret_headers:
            raise ValueError(f"stdio MCP server {server.id} cannot define HTTP endpoint or headers")
        return
    parsed = urlparse(server.endpoint or "")
    host = parsed.hostname
    if parsed.username or parsed.password or not host:
        raise ValueError(f"MCP server {server.id} has an invalid endpoint")
    is_local = host in {"localhost", "127.0.0.1", "::1"}
    try:
        parsed_ip = ipaddress.ip_address(host)
        is_local = parsed_ip.is_loopback
    except ValueError:
        pass
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and local_dev and is_local:
        return
    raise ValueError(f"MCP server {server.id} must use HTTPS (HTTP is allowed only for local development)")


def _validate_admin_catalog(catalog: McpCatalog) -> None:
    for server in catalog.servers.values():
        _validate_admin_server(server)
    unsupported = [
        binding.id
        for binding in catalog.capabilities.values()
        if binding.risk == "high_risk_write" and not supports_high_risk_policy(binding.policy_id)
    ]
    if unsupported:
        raise ValueError(
            "high-risk MCP capabilities require an implemented Host policy: "
            + ", ".join(unsupported)
        )


def required_secret_refs(catalog: McpCatalog) -> set[str]:
    refs: set[str] = set()
    for server in catalog.servers.values():
        refs.update(server.secret_headers.values())
        refs.update(server.secret_arguments.values())
        refs.update(server.secret_environment.values())
    return refs


def _missing_secret_refs(catalog: McpCatalog, secrets: dict[str, str]) -> list[str]:
    settings = get_settings()
    return sorted(
        ref
        for ref in required_secret_refs(catalog)
        if not secrets.get(ref) and not getattr(settings, ref, None)
    )


def _public_catalog(payload: dict[str, Any], secrets: dict[str, str], *, source: str, draft_version: int, active_version: int, published_at: datetime | None) -> dict[str, Any]:
    return {
        "source": source,
        "catalog": payload,
        "secret_refs": {key: bool(value) for key, value in sorted(secrets.items())},
        "draft_version": draft_version,
        "active_version": active_version,
        "published_at": published_at.isoformat() if published_at else None,
    }


async def get_catalog_config(session: AsyncSession) -> McpCatalogConfig | None:
    return await session.get(McpCatalogConfig, _CONFIG_ID)


async def draft_view(session: AsyncSession, *, fallback: McpCatalog) -> dict[str, Any]:
    config = await get_catalog_config(session)
    if config is None or not config.draft_json:
        return _public_catalog(
            _catalog_payload(fallback), {}, source="environment", draft_version=0,
            active_version=0, published_at=None,
        )
    return _public_catalog(
        _json_object(config.draft_json), _decrypt_secrets(config.draft_secrets_enc),
        source="database", draft_version=config.draft_version,
        active_version=config.active_version, published_at=config.published_at,
    )


async def save_draft(
    session: AsyncSession,
    *,
    catalog_payload: dict[str, Any],
    submitted_secrets: dict[str, str],
    actor_id: str,
) -> dict[str, Any]:
    catalog = parse_catalog_payload(catalog_payload)
    config = await get_catalog_config(session)
    existing = _decrypt_secrets(config.draft_secrets_enc) if config is not None else {}
    for name, value in submitted_secrets.items():
        if value.strip():
            existing[name] = value.strip()
    required = required_secret_refs(catalog)
    # Drop secrets no longer referenced, reducing their retention surface.
    secrets = {name: value for name, value in existing.items() if name in required}
    missing = _missing_secret_refs(catalog, secrets)
    if missing:
        raise ValueError(f"missing secret values for: {', '.join(missing)}")
    if config is None:
        config = McpCatalogConfig(id=_CONFIG_ID, draft_version=0, active_version=0)
        session.add(config)
    config.draft_json = json.dumps(_catalog_payload(catalog), ensure_ascii=False, sort_keys=True)
    config.draft_secrets_enc = encrypt(json.dumps(secrets, ensure_ascii=False, sort_keys=True)) if secrets else ""
    config.draft_version = int(config.draft_version or 0) + 1
    config.updated_by = actor_id
    await session.flush()
    return _public_catalog(
        _json_object(config.draft_json), secrets, source="database",
        draft_version=config.draft_version, active_version=config.active_version,
        published_at=config.published_at,
    )


async def publish_draft(session: AsyncSession, *, actor_id: str) -> tuple[dict[str, Any], int]:
    import uuid

    config = await get_catalog_config(session)
    if config is None or not config.draft_json:
        raise ValueError("no MCP catalog draft to publish")
    catalog = parse_catalog_payload(_json_object(config.draft_json))
    secrets = _decrypt_secrets(config.draft_secrets_enc)
    missing = _missing_secret_refs(catalog, secrets)
    if missing:
        raise ValueError(f"missing secret values for: {', '.join(missing)}")
    next_version = int(config.active_version or 0) + 1
    checksum = hashlib.sha256(config.draft_json.encode("utf-8")).hexdigest()
    config.published_json = config.draft_json
    config.published_secrets_enc = config.draft_secrets_enc
    config.active_version = next_version
    config.published_by = actor_id
    config.published_at = _utcnow()
    session.add(
        McpPluginSetRelease(
            version=next_version,
            catalog_json=config.draft_json,
            secrets_enc=config.draft_secrets_enc,
            checksum=checksum,
            published_by=actor_id,
            published_at=config.published_at,
        )
    )
    session.add(
        McpCatalogAudit(
            id=str(uuid.uuid4()), action="publish", version=config.active_version,
            actor_id=actor_id,
            summary_json=json.dumps(
                {
                    "servers": len(catalog.servers),
                    "capabilities": len(catalog.capabilities),
                    "contracts": len(catalog.contracts or {}),
                    "checksum": checksum,
                },
                sort_keys=True,
            ),
        )
    )
    await session.flush()
    return (
        _public_catalog(
            _json_object(config.draft_json), secrets, source="database",
            draft_version=config.draft_version, active_version=config.active_version,
            published_at=config.published_at,
        ),
        config.active_version,
    )


async def published_snapshot(
    session: AsyncSession, *, version: int | None = None
) -> tuple[int, McpCatalog, dict[str, str]] | None:
    """Resolve either the active PluginSet or one immutable historical release."""
    if version is not None:
        release = await session.get(McpPluginSetRelease, version)
        if release is None:
            return None
        return (
            release.version,
            parse_catalog_payload(_json_object(release.catalog_json)),
            _decrypt_secrets(release.secrets_enc),
        )
    config = await get_catalog_config(session)
    if config is None or not config.published_json or config.active_version <= 0:
        return None
    release = await session.get(McpPluginSetRelease, config.active_version)
    if release is not None:
        return (
            release.version,
            parse_catalog_payload(_json_object(release.catalog_json)),
            _decrypt_secrets(release.secrets_enc),
        )
    # Compatibility for a database published by catalog v1 before immutable
    # release rows were introduced. The next publication creates a release.
    return (
        config.active_version,
        parse_catalog_payload(_json_object(config.published_json)),
        _decrypt_secrets(config.published_secrets_enc),
    )


def manager_for_server_test(server_payload: dict[str, Any], *, secrets: dict[str, str]):
    """Create an isolated manager for a transient admin connection check."""
    from .manager import McpConnectionManager
    from src.settings import get_settings

    server = McpServerSpec.model_validate(server_payload)
    _validate_admin_server(server)
    catalog = McpCatalog(servers={server.id: server}, capabilities={})
    missing = sorted(
        set(server.secret_headers.values())
        .union(server.secret_arguments.values(), server.secret_environment.values())
        .difference({key for key, value in secrets.items() if value.strip()})
    )
    if missing:
        raise ValueError(f"missing secret values for: {', '.join(missing)}")
    return McpConnectionManager(catalog=catalog, settings=get_settings(), secret_values=secrets)
