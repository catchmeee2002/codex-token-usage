from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

from codex_token_usage.cli import build_parser, main

from test_scanner import make_home, session_meta, token_event, usage, write_session


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def test_json_output_has_stable_schema(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-25T01:00:00Z"),
            token_event("2026-07-25T01:01:00Z", usage(100, 10), usage(100, 10)),
        ],
    )
    stdout = io.StringIO()
    code = main(
        ["--codex-home", str(home), "--all", "--json", "--timezone", "UTC"],
        now=NOW,
        stdout=stdout,
    )
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["schema_version"] == 1
    assert payload["usage"]["total_tokens"] == 110
    assert payload["auth"]["current_mode"] == "apikey"
    assert "root" in payload["by_thread_type"]


def test_default_window_and_human_output(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-25T01:00:00Z"),
            token_event("2026-07-25T01:01:00Z", usage(25, 5), usage(25, 5)),
        ],
    )
    stdout = io.StringIO()
    code = main(
        ["--codex-home", str(home), "--timezone", "UTC"],
        now=NOW,
        stdout=stdout,
    )
    output = stdout.getvalue()
    assert code == 0
    assert "最近 7 天" in output
    assert "不是全部历史" in output
    assert "查看全部历史：codex-token-usage --all" in output
    assert "总 Token：" in output
    assert "每日总 Token 趋势" in output
    assert "█" in output
    assert "2026-07-25*" in output


def test_all_time_human_output_is_clearly_labeled(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    stdout = io.StringIO()
    code = main(
        ["--codex-home", str(home), "--all", "--timezone", "UTC"],
        now=NOW,
        stdout=stdout,
    )
    output = stdout.getvalue()
    assert code == 0
    assert "统计范围：全部历史" in output
    assert "不是全部历史" not in output


def test_english_human_output_remains_available(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    stdout = io.StringIO()
    code = main(
        ["--codex-home", str(home), "--all", "--lang", "en"],
        now=NOW,
        stdout=stdout,
    )
    output = stdout.getvalue()
    assert code == 0
    assert "Codex token usage" in output
    assert "Scope: all history" in output


def test_no_daily_hides_chart(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    stdout = io.StringIO()
    code = main(
        ["--codex-home", str(home), "--all", "--no-daily"],
        now=NOW,
        stdout=stdout,
    )
    assert code == 0
    assert "每日总 Token 趋势" not in stdout.getvalue()


def test_ui_option_is_available() -> None:
    args = build_parser().parse_args(["--ui"])
    assert args.ui is True


def test_english_help_is_available() -> None:
    help_text = build_parser("en").format_help()
    assert "Audit local Codex token usage" in help_text
    assert "open the full-screen interactive terminal UI" in help_text


def test_ui_rejects_report_filters(tmp_path: Path) -> None:
    stderr = io.StringIO()
    code = main(
        ["--codex-home", str(tmp_path), "--ui", "--all"],
        now=NOW,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == 2
    assert "--ui 只能" in stderr.getvalue()


def test_english_ui_language_is_accepted_before_tty_check(tmp_path: Path) -> None:
    stderr = io.StringIO()
    code = main(
        ["--codex-home", str(tmp_path), "--ui", "--lang", "en"],
        now=NOW,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == 2
    assert "requires an interactive TTY" in stderr.getvalue()


def test_strict_mode_fails_on_auth_warning(tmp_path: Path) -> None:
    home = make_home(tmp_path, auth_mode="chatgpt")
    stdout = io.StringIO()
    code = main(
        ["--codex-home", str(home), "--all", "--strict"],
        now=NOW,
        stdout=stdout,
    )
    assert code == 1
    assert "current_auth_is_not_api_key" in stdout.getvalue()


def test_invalid_filter_combination_returns_usage_error(tmp_path: Path) -> None:
    stderr = io.StringIO()
    code = main(
        ["--codex-home", str(tmp_path), "--all", "--since", "7d"],
        now=NOW,
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == 2
    assert "mutually exclusive" in stderr.getvalue()
