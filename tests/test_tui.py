from datetime import datetime, timezone
from pathlib import Path

from codex_token_usage.chart import build_daily_vertical_chart
from codex_token_usage.model import ScanResult, ScanWindow, Usage
from codex_token_usage.scanner import scan_codex_usage
from codex_token_usage.timeparse import build_window
from codex_token_usage.tui import TokenUsageTui, choice_labels, effort_column_labels, effort_keys

from test_scanner import make_home, session_meta, token_event, usage, write_session


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def test_tui_offers_all_history_and_custom_ranges() -> None:
    assert choice_labels("zh") == [
        "最近 7 天",
        "最近 24 小时",
        "最近 30 天",
        "全部历史",
        "自定义日期",
    ]
    assert choice_labels("en") == [
        "Last 7 days",
        "Last 24 hours",
        "Last 30 days",
        "All history",
        "Custom dates",
    ]


def test_vertical_chart_uses_date_x_axis_and_token_y_axis(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-23T01:00:00Z"),
            token_event("2026-07-23T01:01:00Z", usage(90, 10), usage(90, 10)),
            token_event("2026-07-25T01:01:00Z", usage(290, 30), usage(200, 20)),
        ],
    )
    window = build_window(
        now=NOW,
        timezone_name="UTC",
        all_time=True,
        since=None,
        from_value=None,
        to_value=None,
    )
    result = scan_codex_usage(home, window, now=NOW)
    chart = build_daily_vertical_chart(result, width=50, height=6)
    assert chart is not None
    assert [bucket.total_tokens for bucket in chart.buckets] == [100, 0, 220]
    assert len(chart.lines) == 8
    assert "220" in chart.lines[0]
    assert any("└" in line for line in chart.lines)
    assert "7/23" in chart.lines[-1]
    assert "7/25*" in chart.lines[-1]
    assert any("█" in line for line in chart.lines)

    english = build_daily_vertical_chart(result, width=50, height=6, language="en")
    assert english is not None
    assert english.lines[0].lstrip().startswith("220")

    selected = build_daily_vertical_chart(result, width=50, height=6, selected_index=-1)
    assert selected is not None
    assert selected.selected_index == 2
    assert any("▓" in line for line in selected.lines)


def test_vertical_chart_buckets_long_ranges_without_losing_totals() -> None:
    result = ScanResult(
        generated_at=NOW,
        window=ScanWindow(
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 1, tzinfo=timezone.utc),
            timezone=timezone.utc,
            timezone_name="UTC",
            label="custom range",
        ),
        auth_mode="apikey",
    )
    result.daily = {
        "2020-01-01": Usage(input_tokens=10),
        "2025-12-31": Usage(input_tokens=20),
    }
    chart = build_daily_vertical_chart(result, width=50, height=6)
    assert chart is not None
    assert chart.bucket_days > 1
    assert len(chart.buckets) <= 40
    assert sum(bucket.total_tokens for bucket in chart.buckets) == 30


def test_tui_chart_selection_stops_at_edges() -> None:
    tui = object.__new__(TokenUsageTui)
    tui.chart_bucket_count = 3
    tui.chart_index = 2
    tui._move_chart_selection(1)
    assert tui.chart_index == 2
    tui._move_chart_selection(-1)
    assert tui.chart_index == 1


def test_tui_toggles_between_usage_and_effort_pages() -> None:
    tui = object.__new__(TokenUsageTui)
    tui.page = "usage"
    tui._toggle_page()
    assert tui.page == "effort"
    tui._toggle_page()
    assert tui.page == "usage"


def test_effort_keys_follow_reasoning_level_order() -> None:
    result = ScanResult(
        generated_at=NOW,
        window=ScanWindow(None, NOW, timezone.utc, "UTC", "all time"),
        auth_mode="apikey",
    )
    result.add_effort_usage(Usage(input_tokens=10), effort="ultra", model="gpt-test", turn_key="u")
    result.add_effort_usage(Usage(input_tokens=10), effort="medium", model="gpt-test", turn_key="m")
    result.add_effort_usage(Usage(input_tokens=10), effort="xhigh", model="gpt-test", turn_key="x")
    assert effort_keys(result) == ["medium", "xhigh", "ultra"]


def test_effort_table_headers_are_localized() -> None:
    assert effort_column_labels("zh") == [
        "等级",
        "用量",
        "占比",
        "工作速率",
        "调用中位",
        "回合中位",
        "推理占比",
        "缓存率",
        "样本",
    ]
    assert effort_column_labels("en")[0] == "Effort"
