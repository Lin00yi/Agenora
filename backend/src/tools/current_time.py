"""Current time tool for deterministic date/time answers."""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.tools.base import Tool, ToolResult

_WEEKDAYS_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _system_timezone() -> tuple[tzinfo, str]:
    local_now = datetime.now().astimezone()
    local_tz = local_now.tzinfo
    if local_tz is None:
        return local_now.astimezone().tzinfo or ZoneInfo("UTC"), "system local timezone"
    name = local_now.tzname()
    label = name or str(local_tz) or "system local timezone"
    return local_tz, label


def _resolve_timezone(value: str | None) -> tuple[tzinfo, str, str]:
    requested = (value or "").strip()
    if requested:
        try:
            return ZoneInfo(requested), requested, "requested"
        except ZoneInfoNotFoundError:
            pass
    tz, label = _system_timezone()
    return tz, label, "system"


class CurrentTimeTool(Tool):
    name = "get_current_time"

    def __init__(
        self,
        *,
        now_provider: Callable[[tzinfo], datetime] | None = None,
    ) -> None:
        self._now_provider = now_provider or datetime.now
        self.description = (
            "获取服务端当前日期、时间、星期和时区。适合回答“今天几月几号”、"
            "“现在几点”、以及把今天/明天/后天等相对日期换算成具体日期。"
            "默认使用运行本服务的计算机系统时区，不要用 web_search 查询当前日期或时间。"
        )
        self.input_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA 时区名，例如 Asia/Shanghai 或 America/New_York。"
                        "省略时使用运行本服务的计算机系统时区。"
                    ),
                }
            },
        }

    async def execute(self, timezone: str | None = None) -> ToolResult:
        tz, effective_timezone, timezone_source = _resolve_timezone(timezone)

        now = self._now_provider(tz)
        if now.tzinfo is None:
            now = now.replace(tzinfo=tz)
        else:
            now = now.astimezone(tz)

        today = now.date()
        tomorrow = today + timedelta(days=1)
        day_after_tomorrow = today + timedelta(days=2)
        weekday = _WEEKDAYS_ZH[today.weekday()]
        utc_offset = now.strftime("%z")
        formatted_offset = f"{utc_offset[:3]}:{utc_offset[3:]}" if utc_offset else ""

        text = (
            f"当前日期: {today.isoformat()}\n"
            f"当前时间: {now.strftime('%H:%M:%S')}\n"
            f"星期: {weekday}\n"
            f"时区: {effective_timezone}"
            f"{f' (UTC{formatted_offset})' if formatted_offset else ''}"
            f"{'，系统时区' if timezone_source == 'system' else ''}\n"
            f"今天 = {today.isoformat()}\n"
            f"明天 = {tomorrow.isoformat()}\n"
            f"后天 = {day_after_tomorrow.isoformat()}"
        )
        return ToolResult(
            text=text,
            latency_ms=0,
            raw={
                "date": today.isoformat(),
                "time": now.strftime("%H:%M:%S"),
                "weekday": weekday,
                "timezone": effective_timezone,
                "timezone_source": timezone_source,
                "utc_offset": formatted_offset,
                "today": today.isoformat(),
                "tomorrow": tomorrow.isoformat(),
                "day_after_tomorrow": day_after_tomorrow.isoformat(),
            },
        )
