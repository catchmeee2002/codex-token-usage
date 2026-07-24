from datetime import datetime, timedelta, timezone

import pytest

from codex_token_usage.timeparse import TimeParseError, build_window, parse_duration


def test_parse_duration_accepts_supported_units() -> None:
    assert parse_duration("90m") == timedelta(minutes=90)
    assert parse_duration("24h") == timedelta(days=1)
    assert parse_duration("7d") == timedelta(days=7)
    assert parse_duration("2w") == timedelta(days=14)


@pytest.mark.parametrize("value", ["", "0d", "1.5d", "7days", "-1h"])
def test_parse_duration_rejects_ambiguous_values(value: str) -> None:
    with pytest.raises(TimeParseError):
        parse_duration(value)


def test_default_window_is_rolling_seven_days() -> None:
    now = datetime(2026, 7, 25, 2, 0, tzinfo=timezone.utc)
    window = build_window(
        now=now,
        timezone_name="UTC",
        all_time=False,
        since=None,
        from_value=None,
        to_value=None,
    )
    assert window.start == now - timedelta(days=7)
    assert window.end == now
    assert window.label == "rolling 7d"


def test_date_to_value_includes_the_whole_local_day() -> None:
    window = build_window(
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
        timezone_name="Asia/Shanghai",
        all_time=False,
        since=None,
        from_value="2026-07-18",
        to_value="2026-07-18",
    )
    assert window.start == datetime(2026, 7, 17, 16, 0, tzinfo=timezone.utc)
    assert window.end == datetime(2026, 7, 18, 16, 0, tzinfo=timezone.utc)


def test_filter_modes_are_mutually_exclusive() -> None:
    with pytest.raises(TimeParseError):
        build_window(
            now=datetime.now(timezone.utc),
            timezone_name="UTC",
            all_time=True,
            since="7d",
            from_value=None,
            to_value=None,
        )
