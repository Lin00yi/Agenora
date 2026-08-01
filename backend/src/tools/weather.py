"""Weather tool — calls QWeather v7/weather/3d."""
from __future__ import annotations

import re
from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from src.settings import get_settings
from src.tools.base import Tool, ToolResult

DEFAULT_TRAVEL_TIMEZONE = "Asia/Shanghai"


def _today(timezone: str = DEFAULT_TRAVEL_TIMEZONE) -> Date:
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo(DEFAULT_TRAVEL_TIMEZONE)
    return datetime.now(tz).date()


def normalize_weather_date(value: str, *, today: Date | None = None) -> str:
    """Normalize relative travel dates to YYYY-MM-DD.

    The model is instructed to pass ISO dates, but this keeps get_weather
    deterministic when it still passes terms like "明天".
    """
    raw = (value or "").strip()
    if not raw:
        return raw

    iso = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        return Date(year, month, day).isoformat()

    compact = re.sub(r"\s+", "", raw).lower()
    base = today or _today()
    offsets = {
        "today": 0,
        "今天": 0,
        "tomorrow": 1,
        "明天": 1,
        "后天": 2,
        "後天": 2,
        "大后天": 3,
        "大後天": 3,
    }
    for key in ("大后天", "大後天", "tomorrow", "today", "后天", "後天", "明天", "今天"):
        if key in compact:
            return (base + timedelta(days=offsets[key])).isoformat()

    return raw


# Common city → location ID (QWeather LocationID). Extend as needed.
CITY_TO_LOCATION = {
    "上海": "101020100",
    "北京": "101010100",
    "成都": "101270101",
    "杭州": "101210101",
    "深圳": "101280601",
    "广州": "101280101",
}


class WeatherTool(Tool):
    name = "get_weather"
    description = "查询某城市某日期 (YYYY-MM-DD) 的天气。返回简短文本：城市 日期: 天气描述, 温度范围, 风力。"
    input_schema = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "中文城市名 (如 上海/北京)"},
            "date": {"type": "string", "format": "date", "description": "YYYY-MM-DD"},
        },
        "required": ["city", "date"],
    }

    async def execute(self, city: str, date: str) -> ToolResult:
        date = normalize_weather_date(date)
        s = get_settings()
        location = CITY_TO_LOCATION.get(city)
        if not location:
            return ToolResult(
                text=f"暂不支持城市: {city} (v1 仅支持: {'、'.join(CITY_TO_LOCATION.keys())})",
                latency_ms=0,
            )
        if not s.qweather_api_key:
            # Mock for local dev when key missing
            return ToolResult(
                text=f"{city} {date}: 多云转晴, 18-26°C, 风力 2 级 (mock — 配置 QWEATHER_API_KEY 启用真实查询)",
                latency_ms=0,
                raw={"mock": True},
            )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://devapi.qweather.com/v7/weather/3d",
                params={"location": location, "key": s.qweather_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        daily = data.get("daily", [])
        target = next((d for d in daily if d.get("fxDate") == date), None)
        if not target:
            return ToolResult(
                text=f"{city} {date}: 查不到该日期的预报 (QWeather 仅支持未来 3 天)",
                latency_ms=0,
                raw=data,
            )
        text = (
            f"{city} {date}: {target['textDay']}, "
            f"{target['tempMin']}-{target['tempMax']}°C, "
            f"风力 {target['windScaleDay']} 级"
        )
        return ToolResult(text=text, latency_ms=0, raw=target)
