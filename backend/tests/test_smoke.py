"""Non-network smoke tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.safety.input_filter import sanitize_user_input
from src.safety.output_filter import redact_pii
from src.safety.tool_guard import is_tool_allowed
from src.tools.base import build_default_registry


def test_input_sanitize_passes_normal():
    text, blocked = sanitize_user_input("May 2 Shanghai sour fish")
    assert text == "May 2 Shanghai sour fish"
    assert blocked is None


def test_input_sanitize_blocks_dangerous():
    _, blocked = sanitize_user_input("rm -rf / && eat food")
    assert blocked is not None


def test_output_redact_phone():
    out = redact_pii("contact: 13800138000 thanks")
    assert "13800138000" not in out
    assert "[phone redacted]" in out


def test_tool_guard_allows_registered():
    # General chat registered tools must pass the whitelist.
    reg = build_default_registry()
    ok, _ = is_tool_allowed("web_search", reg.names())
    assert ok
    ok, _ = is_tool_allowed("get_current_time", reg.names())
    assert ok


def test_tool_guard_blocks_unknown():
    ok, reason = is_tool_allowed("execute_shell", ["web_search"])
    assert not ok
    assert reason


def test_default_registry_has_general_chat_tools():
    assert build_default_registry().names() == ["get_current_time", "web_search"]


@pytest.mark.asyncio
async def test_current_time_tool_returns_deterministic_relative_dates():
    from src.tools.current_time import CurrentTimeTool

    tool = CurrentTimeTool(
        now_provider=lambda tz: datetime(2026, 8, 2, 9, 30, tzinfo=tz),
    )
    result = await tool.execute()

    assert "当前日期: 2026-08-02" in result.text
    assert "明天 = 2026-08-03" in result.text
    assert result.raw["weekday"] == "星期日"
    assert result.raw["timezone_source"] == "system"


@pytest.mark.asyncio
async def test_current_time_tool_honors_requested_timezone():
    from src.tools.current_time import CurrentTimeTool

    tool = CurrentTimeTool(
        now_provider=lambda tz: datetime(2026, 8, 2, 1, 30, tzinfo=ZoneInfo("UTC")).astimezone(tz),
    )
    result = await tool.execute(timezone="America/New_York")

    assert "当前日期: 2026-08-01" in result.text
    assert result.raw["timezone"] == "America/New_York"
    assert result.raw["timezone_source"] == "requested"


def test_user_kb_registry_has_kb_report_tool():
    from types import SimpleNamespace

    kb = SimpleNamespace(
        id="user-kb",
        name="User KB",
        description="",
        collection_name="kb_user",
        is_system=False,
        grouping_enabled=False,
    )
    names = build_default_registry(kb).names()
    assert "search_kb" in names
    assert "generate_kb_report" in names


def test_web_search_provider_defaults_to_duckduckgo(monkeypatch):
    from src.settings import get_settings
    from src.tools.search_providers import DuckDuckGoSearchProvider, get_search_provider

    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "duckduckgo")
    get_settings.cache_clear()
    try:
        assert isinstance(get_search_provider(), DuckDuckGoSearchProvider)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_production_init_db_never_bootstraps_schema(tmp_path, monkeypatch):
    """Production API/worker startup must leave DDL to the migrate job."""
    db_file = tmp_path / "production.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SCHEMA_BOOTSTRAP", "true")

    from sqlalchemy import inspect

    from src.settings import get_settings
    import src.storage.database as database

    get_settings.cache_clear()
    database._engine = None
    database._session_factory = None
    try:
        await database.init_db()
        async with database.get_engine().connect() as connection:
            tables = await connection.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
        assert tables == []
    finally:
        if database._engine is not None:
            await database._engine.dispose()
        database._engine = None
        database._session_factory = None
        get_settings.cache_clear()
