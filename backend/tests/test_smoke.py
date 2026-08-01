"""Non-network smoke tests."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

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
    # General chat registers only web_search; any registered tool must pass.
    reg = build_default_registry()
    ok, _ = is_tool_allowed("web_search", reg.names())
    assert ok


def test_tool_guard_blocks_unknown():
    ok, reason = is_tool_allowed("execute_shell", ["get_weather"])
    assert not ok
    assert reason


def test_default_registry_is_web_search_only():
    assert build_default_registry().names() == ["web_search"]


def test_travel_kb_registry_has_travel_tools():
    from types import SimpleNamespace

    from src.kb.models import SYSTEM_TRAVEL_KB_ID

    names = build_default_registry(SimpleNamespace(id=SYSTEM_TRAVEL_KB_ID)).names()
    assert "get_weather" in names
    assert "search_restaurant_kb" in names
    assert "amap_search" in names
    assert "generate_travel_report" in names


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


def test_weather_date_normalization_handles_relative_dates():
    from src.tools.weather import normalize_weather_date

    today = date(2026, 8, 1)
    assert normalize_weather_date("2026-08-03", today=today) == "2026-08-03"
    assert normalize_weather_date("2026/8/3", today=today) == "2026-08-03"
    assert normalize_weather_date("明天", today=today) == "2026-08-02"
    assert normalize_weather_date("后天", today=today) == "2026-08-03"
    assert normalize_weather_date("大后天", today=today) == "2026-08-04"


def test_travel_prompt_injects_current_date_context():
    from src.agent.prompts import build_travel_system_prompt

    prompt = build_travel_system_prompt(
        now=datetime(2026, 8, 1, 12, 0, tzinfo=ZoneInfo("UTC")),
        timezone="Asia/Shanghai",
    )
    assert "当前日期: 2026-08-01" in prompt
    assert "明天 = 2026-08-02" in prompt
    assert "不要为了判断相对日期对应哪一天调用 web_search" in prompt
