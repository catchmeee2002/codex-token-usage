from __future__ import annotations

import re
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .model import ScanWindow


_DURATION_RE = re.compile(r"^([1-9][0-9]*)([mhdw])$")
_DURATION_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


class TimeParseError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedTimezone:
    value: tzinfo
    name: str


def resolve_timezone(name: str | None) -> ResolvedTimezone:
    if name:
        try:
            return ResolvedTimezone(ZoneInfo(name), name)
        except ZoneInfoNotFoundError as exc:
            raise TimeParseError(f"unknown IANA timezone: {name}") from exc

    candidates: list[str] = []
    configured = os.environ.get("TZ", "").strip().removeprefix(":")
    if configured:
        candidates.append(configured)
    try:
        configured = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if configured:
            candidates.append(configured)
    except OSError:
        pass
    for localtime_path in (Path("/etc/localtime"), Path("/var/db/timezone/zoneinfo")):
        try:
            resolved = str(localtime_path.resolve())
        except OSError:
            continue
        marker = "/zoneinfo/"
        if marker in resolved:
            candidates.append(resolved.split(marker, 1)[1])
    for candidate in candidates:
        try:
            return ResolvedTimezone(ZoneInfo(candidate), candidate)
        except ZoneInfoNotFoundError:
            continue

    local = datetime.now().astimezone().tzinfo or timezone.utc
    local_name = getattr(local, "key", None) or str(local)
    return ResolvedTimezone(local, local_name)


def parse_duration(raw: str) -> timedelta:
    match = _DURATION_RE.fullmatch(raw.strip())
    if not match:
        raise TimeParseError("duration must be a positive integer followed by m, h, d, or w")
    amount, unit = match.groups()
    return timedelta(seconds=int(amount) * _DURATION_SECONDS[unit])


def parse_boundary(raw: str, tz: tzinfo, *, end_date_inclusive: bool) -> datetime:
    value = raw.strip()
    try:
        if "T" not in value and " " not in value:
            parsed_date = date.fromisoformat(value)
            if end_date_inclusive:
                parsed_date += timedelta(days=1)
            return datetime.combine(parsed_date, time.min, tzinfo=tz).astimezone(timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimeParseError(f"invalid ISO date or datetime: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def build_window(
    *,
    now: datetime,
    timezone_name: str | None,
    all_time: bool,
    since: str | None,
    from_value: str | None,
    to_value: str | None,
) -> ScanWindow:
    resolved = resolve_timezone(timezone_name)
    now_utc = now.astimezone(timezone.utc)

    selected = sum(bool(value) for value in (all_time, since, from_value or to_value))
    if selected > 1:
        raise TimeParseError("--all, --since, and --from/--to are mutually exclusive")

    if all_time:
        return ScanWindow(None, now_utc, resolved.value, resolved.name, "all time")
    if from_value or to_value:
        start = (
            parse_boundary(from_value, resolved.value, end_date_inclusive=False)
            if from_value
            else None
        )
        end = (
            parse_boundary(to_value, resolved.value, end_date_inclusive=True)
            if to_value
            else now_utc
        )
        if start is not None and start >= end:
            raise TimeParseError("the start of the range must be earlier than the end")
        return ScanWindow(start, end, resolved.value, resolved.name, "custom range")

    duration_text = since or "7d"
    duration = parse_duration(duration_text)
    return ScanWindow(
        now_utc - duration,
        now_utc,
        resolved.value,
        resolved.name,
        f"rolling {duration_text}",
    )
