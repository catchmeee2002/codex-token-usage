from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, timezone

import pytest

from codex_token_usage.cli import main
from codex_token_usage.chart import ChartBucket, single_local_day
from codex_token_usage.scanner import scan_codex_usage
from codex_token_usage.timeparse import build_window
from codex_token_usage.tui import TokenUsageTui, choice_labels

from test_scanner import (
    make_home,
    marker_event,
    session_meta,
    subagent_trigger_event,
    task_complete_event,
    task_started_event,
    token_event,
    turn_context_event,
    usage,
    write_session,
)


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
AFTER_SELECTED_DAY = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
AFTER_DST = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
_EXACT_HOUR_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}\s+)?"
    r"(?P<hour>[01]\d|2[0-3]):00\D+"
    r"(?:[01]\d|2[0-4]):00\s+(?P<tokens>[\d,]+)$"
)


def render_text(home, *args: str, now: datetime = NOW, language: str = "zh") -> str:
    stdout = io.StringIO()
    code = main(
        [
            "--codex-home",
            str(home),
            "--text",
            "--lang",
            language,
            *args,
        ],
        now=now,
        stdout=stdout,
    )
    assert code == 0
    return stdout.getvalue()


def parse_exact_hour_values(output: str) -> dict[int, int]:
    values: dict[int, int] = {}
    for line in output.splitlines():
        match = _EXACT_HOUR_RE.fullmatch(line.strip())
        if match:
            values[int(match.group("hour"))] = int(match.group("tokens").replace(",", ""))
    return values


def test_single_day_hourly_text_preserves_counting_invariants(tmp_path) -> None:
    home = make_home(tmp_path)
    first = token_event("2026-07-25T00:00:00Z", usage(10, 1), usage(10, 1))
    noon = token_event("2026-07-25T12:34:00Z", usage(30, 3), usage(20, 2))
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-25T00:00:00Z"),
            first,
            noon,
            token_event("2026-07-25T12:35:00Z", usage(30, 3), usage(20, 2)),
            token_event("2026-07-25T23:59:59Z", usage(60, 6), usage(30, 3)),
        ],
    )
    write_session(
        home,
        "copied-root-event",
        [session_meta("copy", "2026-07-25T12:33:00Z"), noon],
    )
    write_session(
        home,
        "imported",
        [
            session_meta("imported", "2026-07-25T04:55:00Z"),
            marker_event("2026-07-25T04:59:00Z"),
            token_event("2026-07-25T04:58:00Z", usage(100, 10), usage(100, 10)),
            token_event("2026-07-25T05:00:00Z", usage(150, 15), usage(50, 5)),
        ],
    )
    write_session(
        home,
        "subagent",
        [
            session_meta(
                "subagent",
                "2026-07-25T17:00:00Z",
                thread_source="subagent",
            ),
            token_event("2026-07-25T17:01:00Z", usage(200, 20), usage(200, 20)),
            subagent_trigger_event("2026-07-25T17:59:00Z"),
            token_event("2026-07-25T18:00:00Z", usage(260, 26), usage(60, 6)),
        ],
    )

    output = render_text(
        home,
        "--from",
        "2026-07-25",
        "--to",
        "2026-07-25",
        "--timezone",
        "UTC",
        now=AFTER_SELECTED_DAY,
    )
    hourly = parse_exact_hour_values(output)

    assert "单日小时分布" in output
    assert "每小时用量" in output
    assert "精确值" in output
    assert set(hourly) == set(range(24))
    assert hourly == {
        hour: {0: 11, 5: 55, 12: 22, 18: 66, 23: 33}.get(hour, 0)
        for hour in range(24)
    }
    assert sum(hourly.values()) == 187
    assert re.search(r"总 Token：\s+187\b", output)
    assert re.search(r"排除的导入历史事件：\s+1\b", output)
    assert re.search(r"排除子代理继承历史：\s+1\b", output)
    assert re.search(r"忽略重复快照：\s+1\b", output)
    assert re.search(r"忽略完全重复事件：\s+1\b", output)


def test_single_day_hourly_uses_selected_timezone_day_edges(tmp_path) -> None:
    home = make_home(tmp_path)
    records = [
        ("before", "2026-07-24T15:59:59Z", 5),
        ("start", "2026-07-24T16:00:00Z", 11),
        ("end-minus", "2026-07-25T15:59:59Z", 22),
        ("end", "2026-07-25T16:00:00Z", 44),
    ]
    for name, timestamp, tokens in records:
        write_session(
            home,
            name,
            [
                session_meta(name, timestamp),
                token_event(timestamp, usage(tokens, 0), usage(tokens, 0)),
            ],
        )

    output = render_text(
        home,
        "--from",
        "2026-07-25",
        "--to",
        "2026-07-25",
        "--timezone",
        "Asia/Shanghai",
        now=AFTER_SELECTED_DAY,
    )
    hourly = parse_exact_hour_values(output)

    assert len(hourly) == 24
    assert hourly[0] == 11
    assert hourly[23] == 22
    assert sum(hourly.values()) == 33
    assert re.search(r"总 Token：\s+33\b", output)


def test_spring_forward_day_keeps_a_zero_wall_clock_hour(tmp_path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "spring-forward",
        [
            session_meta("spring", "2026-03-08T06:00:00Z"),
            token_event("2026-03-08T06:30:00Z", usage(10, 1), usage(10, 1)),
            token_event("2026-03-08T07:30:00Z", usage(30, 3), usage(20, 2)),
        ],
    )

    output = render_text(
        home,
        "--from",
        "2026-03-08",
        "--to",
        "2026-03-08",
        "--timezone",
        "America/New_York",
        now=AFTER_DST,
    )
    hourly = parse_exact_hour_values(output)

    assert set(hourly) == set(range(24))
    assert hourly[1] == 11
    assert hourly[2] == 0
    assert hourly[3] == 22
    assert sum(hourly.values()) == 33


def test_fall_back_merges_repeated_wall_clock_hour(tmp_path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "fall-back",
        [
            session_meta("fall", "2026-11-01T05:00:00Z"),
            token_event("2026-11-01T05:30:00Z", usage(10, 1), usage(10, 1)),
            token_event("2026-11-01T06:30:00Z", usage(30, 3), usage(20, 2)),
        ],
    )

    output = render_text(
        home,
        "--from",
        "2026-11-01",
        "--to",
        "2026-11-01",
        "--timezone",
        "America/New_York",
        now=AFTER_DST,
    )
    hourly = parse_exact_hour_values(output)

    assert set(hourly) == set(range(24))
    assert hourly[1] == 33
    assert sum(hourly.values()) == 33


@pytest.mark.parametrize(
    "range_args",
    [
        ("--since", "24h"),
        ("--from", "2026-07-24", "--to", "2026-07-25"),
        ("--from", "2026-07-25T01:00:00Z", "--to", "2026-07-25T02:00:00Z"),
        ("--all",),
    ],
)
def test_other_text_ranges_keep_daily_distribution(tmp_path, range_args) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-25T01:00:00Z"),
            token_event("2026-07-25T01:30:00Z", usage(10, 1), usage(10, 1)),
        ],
    )

    output = render_text(home, *range_args, "--timezone", "UTC")

    assert "每日用量" in output
    assert "每小时用量" not in output


def test_rolling_twenty_four_hours_ending_at_local_midnight_stays_daily(tmp_path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-24T12:00:00Z"),
            token_event("2026-07-24T12:30:00Z", usage(10, 1), usage(10, 1)),
        ],
    )

    output = render_text(
        home,
        "--since",
        "24h",
        "--timezone",
        "UTC",
        now=datetime(2026, 7, 25, 0, 0, tzinfo=timezone.utc),
    )

    assert "最近 24 小时" in output
    assert "每日用量" in output
    assert "每小时用量" not in output


def test_empty_and_future_days_still_render_twenty_four_zero_hours(tmp_path) -> None:
    home = make_home(tmp_path)

    past = render_text(
        home,
        "--from",
        "2026-07-24",
        "--to",
        "2026-07-24",
        "--timezone",
        "UTC",
    )
    future = render_text(
        home,
        "--from",
        "2026-07-26",
        "--to",
        "2026-07-26",
        "--timezone",
        "UTC",
    )

    assert parse_exact_hour_values(past) == {hour: 0 for hour in range(24)}
    assert parse_exact_hour_values(future) == {hour: 0 for hour in range(24)}
    assert "当日未结束" not in past
    assert "当日未结束" not in future


def test_today_is_marked_in_progress(tmp_path) -> None:
    home = make_home(tmp_path)
    output = render_text(
        home,
        "--from",
        "2026-07-25",
        "--to",
        "2026-07-25",
        "--timezone",
        "UTC",
    )

    assert "当日未结束" in output
    assert len(parse_exact_hour_values(output)) == 24


def test_no_daily_hides_single_day_hourly_chart_and_exact_values(tmp_path) -> None:
    home = make_home(tmp_path)
    output = render_text(
        home,
        "--from",
        "2026-07-25",
        "--to",
        "2026-07-25",
        "--timezone",
        "UTC",
        "--no-daily",
    )

    assert "单日小时分布" in output
    assert "Token ↑" not in output
    assert "每小时用量" not in output
    assert "精确值" not in output


def test_same_day_json_keeps_schema_one_without_hourly_field(tmp_path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-25T01:00:00Z"),
            token_event("2026-07-25T01:30:00Z", usage(10, 1), usage(10, 1)),
        ],
    )
    stdout = io.StringIO()
    code = main(
        [
            "--codex-home",
            str(home),
            "--json",
            "--from",
            "2026-07-25",
            "--to",
            "2026-07-25",
            "--timezone",
            "UTC",
        ],
        now=AFTER_SELECTED_DAY,
        stdout=stdout,
    )
    payload = json.loads(stdout.getvalue())

    assert code == 0
    assert payload["schema_version"] == 1
    assert payload["usage"]["total_tokens"] == 11
    assert payload["daily"]["2026-07-25"]["total_tokens"] == 11
    assert "hourly" not in payload


def test_english_single_day_hourly_labels_are_available(tmp_path) -> None:
    home = make_home(tmp_path)
    output = render_text(
        home,
        "--from",
        "2026-07-24",
        "--to",
        "2026-07-24",
        "--timezone",
        "UTC",
        language="en",
    )

    assert "Single-day hourly" in output
    assert "Hourly usage" in output
    assert "Exact values" in output
    assert len(parse_exact_hour_values(output)) == 24


def test_tui_uses_rolling_label_and_removes_single_day_menu() -> None:
    chinese = choice_labels("zh")
    english = choice_labels("en")

    assert "单日小时分布" not in chinese
    assert "Single-day hourly" not in english
    assert "滚动 24 小时" in chinese
    assert "Rolling 24 hours" in english


def test_tui_hourly_chart_selection_stops_at_zero_and_twenty_three() -> None:
    tui = object.__new__(TokenUsageTui)
    tui.chart_bucket_count = 24

    tui.chart_index = 0
    tui._move_chart_selection(-1)
    assert tui.chart_index == 0

    tui.chart_index = 23
    tui._move_chart_selection(1)
    assert tui.chart_index == 23


@pytest.mark.parametrize(
    ("event_hour", "selected_index"),
    [(None, 0), (12, 5)],
)
def test_selected_zero_hour_has_visible_hourly_chart_highlight(
    tmp_path,
    event_hour,
    selected_index,
) -> None:
    from codex_token_usage.chart import build_hourly_vertical_chart

    home = make_home(tmp_path)
    if event_hour is not None:
        timestamp = f"2026-07-25T{event_hour:02d}:30:00Z"
        write_session(
            home,
            "root",
            [
                session_meta("root", timestamp),
                token_event(timestamp, usage(10, 1), usage(10, 1)),
            ],
        )
    window = build_window(
        now=AFTER_SELECTED_DAY,
        timezone_name="UTC",
        all_time=False,
        since=None,
        from_value="2026-07-25",
        to_value="2026-07-25",
    )
    result = scan_codex_usage(home, window, now=AFTER_SELECTED_DAY)

    chart = build_hourly_vertical_chart(
        result,
        width=80,
        height=6,
        selected_index=selected_index,
    )

    assert chart is not None
    assert len(chart.buckets) == 24
    assert chart.buckets[selected_index].total_tokens == 0
    assert chart.selected_index == selected_index
    assert any("▓" in line for line in chart.lines)


class _FakeScreen:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def make_test_tui(monkeypatch, home) -> TokenUsageTui:
    monkeypatch.setattr("codex_token_usage.tui.curses.curs_set", lambda *_args: None)
    monkeypatch.setattr("codex_token_usage.tui.curses.has_colors", lambda: False)
    tui = TokenUsageTui(
        _FakeScreen(),
        codex_home=home,
        now=AFTER_SELECTED_DAY,
        timezone_name="UTC",
        language="zh",
    )
    monkeypatch.setattr(tui, "_draw", lambda: None)
    return tui


def load_default_range(tui: TokenUsageTui) -> None:
    tui._load(0)
    assert tui.result is not None


def test_single_day_bucket_drills_into_hourly_view(tmp_path, monkeypatch) -> None:
    tui = make_test_tui(monkeypatch, make_home(tmp_path))
    load_default_range(tui)
    parent = tui.result
    selected_day = date(2026, 7, 25)
    tui.selected_daily_bucket = ChartBucket(selected_day, selected_day, 0, False)

    tui._drill_down()

    assert tui.view_kind == "hourly"
    assert single_local_day(tui.result) == selected_day
    assert len(tui.view_stack) == 1
    assert tui.view_stack[0].result is parent


def test_multi_day_bucket_zooms_before_hourly_drilldown(tmp_path, monkeypatch) -> None:
    tui = make_test_tui(monkeypatch, make_home(tmp_path))
    load_default_range(tui)
    parent = tui.result
    tui.chart_index = 3
    tui.selected_daily_bucket = ChartBucket(
        date(2026, 7, 20),
        date(2026, 7, 25),
        0,
        False,
    )

    tui._drill_down()
    zoom = tui.result
    assert tui.view_kind == "zoom"
    assert single_local_day(zoom) is None
    assert len(tui.view_stack) == 1

    selected_day = date(2026, 7, 24)
    tui.selected_daily_bucket = ChartBucket(selected_day, selected_day, 0, False)
    tui._drill_down()
    assert tui.view_kind == "hourly"
    assert single_local_day(tui.result) == selected_day
    assert len(tui.view_stack) == 2

    tui._go_back()
    assert tui.view_kind == "zoom"
    assert tui.result is zoom
    tui._go_back()
    assert tui.view_kind == "range"
    assert tui.result is parent
    assert tui.chart_index == 3


def test_hourly_brackets_change_day_and_stop_at_today(tmp_path, monkeypatch) -> None:
    tui = make_test_tui(monkeypatch, make_home(tmp_path))
    load_default_range(tui)
    selected_day = date(2026, 7, 25)
    tui.selected_daily_bucket = ChartBucket(selected_day, selected_day, 0, False)
    tui._drill_down()

    tui._move_hourly_day(-1)
    assert single_local_day(tui.result) == date(2026, 7, 24)
    tui._move_hourly_day(1)
    assert single_local_day(tui.result) == selected_day

    today = tui.result.generated_at.astimezone(tui.result.window.timezone).date()
    tui.result = scan_codex_usage(
        tui.codex_home,
        tui._window_for_dates(
            today,
            today,
            timezone_name=tui.result.window.timezone_name,
            label="single day",
        ),
        now=tui.result.generated_at,
    )
    before = tui.result
    tui._move_hourly_day(1)
    assert tui.result is before
    assert tui.status == tui._t("today_limit")


def test_language_switch_preserves_drilldown_state(tmp_path, monkeypatch) -> None:
    tui = make_test_tui(monkeypatch, make_home(tmp_path))
    load_default_range(tui)
    selected_day = date(2026, 7, 25)
    tui.selected_daily_bucket = ChartBucket(selected_day, selected_day, 0, False)
    tui._drill_down()
    previous_result = tui.result

    tui._toggle_language()

    assert tui.language == "en"
    assert tui.view_kind == "hourly"
    assert tui.result is previous_result


def test_refresh_preserves_hourly_window_and_parent_stack(tmp_path, monkeypatch) -> None:
    tui = make_test_tui(monkeypatch, make_home(tmp_path))
    load_default_range(tui)
    selected_day = date(2026, 7, 25)
    tui.selected_daily_bucket = ChartBucket(selected_day, selected_day, 0, False)
    tui._drill_down()
    previous_result = tui.result
    previous_stack = list(tui.view_stack)

    tui._refresh_current()

    assert tui.view_kind == "hourly"
    assert single_local_day(tui.result) == selected_day
    assert tui.result is not previous_result
    assert tui.view_stack == previous_stack


def test_enter_drills_current_range_but_applies_other_menu_choice() -> None:
    class Screen:
        def __init__(self, keys):
            self.keys = iter(keys)

        def getch(self):
            return next(self.keys)

    current = object.__new__(TokenUsageTui)
    current.screen = Screen((10, ord("q")))
    current.cursor = 0
    current.active_choice = 0
    current._draw = lambda: None
    current_calls = []
    current._load = lambda index, **kwargs: current_calls.append(("load", index, kwargs))
    current._drill_down = lambda: current_calls.append(("drill",))
    assert current.run() == 0
    assert current_calls == [("load", 0, {}), ("drill",)]

    other = object.__new__(TokenUsageTui)
    other.screen = Screen((10, ord("q")))
    other.cursor = 1
    other.active_choice = 0
    other._draw = lambda: None
    other_calls = []
    other._load = lambda index, **kwargs: other_calls.append(("load", index, kwargs))
    other._drill_down = lambda: other_calls.append(("drill",))
    assert other.run() == 0
    assert other_calls == [("load", 0, {}), ("load", 1, {})]


def test_effort_totals_still_cover_the_whole_selected_day(tmp_path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "effort",
        [
            session_meta("root", "2026-07-25T01:00:00Z"),
            task_started_event("2026-07-25T01:00:00Z", "turn-one"),
            turn_context_event("2026-07-25T01:00:01Z", "turn-one", effort="high"),
            token_event("2026-07-25T01:30:00Z", usage(10, 1), usage(10, 1)),
            task_complete_event("2026-07-25T01:31:00Z", "turn-one"),
            task_started_event("2026-07-25T23:00:00Z", "turn-two"),
            turn_context_event("2026-07-25T23:00:01Z", "turn-two", effort="high"),
            token_event("2026-07-25T23:30:00Z", usage(30, 3), usage(20, 2)),
            task_complete_event("2026-07-25T23:31:00Z", "turn-two"),
        ],
    )
    window = build_window(
        now=NOW,
        timezone_name="UTC",
        all_time=False,
        since=None,
        from_value="2026-07-25",
        to_value="2026-07-25",
    )

    result = scan_codex_usage(home, window, now=AFTER_SELECTED_DAY)

    assert result.usage.total_tokens == 33
    assert result.by_effort["high"].usage.total_tokens == 33
    assert result.by_effort["high"].turns == 2
