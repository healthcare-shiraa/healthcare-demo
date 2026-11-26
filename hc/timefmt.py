"""التخزين بالتوقيت العالمي UTC، والعرض بالمنطقة الزمنية المحددة في HC_DISPLAY_TZ."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_display(value: str | None, tz_name: str) -> str:
    if not value:
        return "—"
    return parse_utc(value).astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")


def fmt_utc(dt: datetime) -> str:
    """الصيغة النصية الموحدة للتخزين: YYYY-MM-DDTHH:MM:SS.ffffffZ"""
    if dt.tzinfo is None:
        raise ValueError("الوقت يجب أن يحمل منطقة زمنية")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def local_to_utc(date_value, time_value, tz_name: str) -> datetime:
    """يحوّل تاريخًا ووقتًا أدخلهما المستخدم بتوقيت العرض إلى UTC."""
    naive = datetime.combine(date_value, time_value)
    return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def to_display_dt(dt: datetime | None, tz_name: str) -> str:
    return "—" if dt is None else dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")


__all__ = ["UTC", "parse_utc", "to_display", "fmt_utc", "local_to_utc", "to_display_dt", "timedelta"]
