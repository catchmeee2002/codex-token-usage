from datetime import datetime, timezone
from pathlib import Path

from codex_token_usage.scanner import scan_codex_usage
from codex_token_usage.timeparse import build_window
from codex_token_usage.tui import build_chart_rows, choice_labels

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


def test_chart_rows_scale_daily_totals(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-24T01:00:00Z"),
            token_event("2026-07-24T01:01:00Z", usage(90, 10), usage(90, 10)),
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
    rows = build_chart_rows(result, width=50, limit=10)
    assert len(rows) == 2
    assert rows[0].startswith("07-24 ")
    assert rows[1].startswith("07-25*")
    assert rows[1].count("█") > rows[0].count("█")

    english_rows = build_chart_rows(result, width=50, limit=10, language="en")
    assert english_rows[0].endswith("100")
    assert english_rows[1].endswith("220")
