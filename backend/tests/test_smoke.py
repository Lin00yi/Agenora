"""Non-network smoke tests."""

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
