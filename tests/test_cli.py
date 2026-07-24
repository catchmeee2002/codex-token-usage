from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

from codex_token_usage.cli import main

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
    assert "rolling 7d" in output
    assert "Total tokens:" in output
    assert "2026-07-25" in output


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
