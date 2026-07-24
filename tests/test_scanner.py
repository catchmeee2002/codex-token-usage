from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from codex_token_usage.model import ScanWindow
from codex_token_usage.scanner import IMPORT_MARKER, scan_codex_usage


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def usage(
    input_tokens: int,
    output_tokens: int,
    *,
    cached: int = 0,
    reasoning: int = 0,
    total_tokens: int | None = None,
) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": 0,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning,
        "total_tokens": total_tokens if total_tokens is not None else input_tokens + output_tokens,
    }


def session_meta(
    thread_id: str,
    timestamp: str,
    *,
    thread_source: str = "user",
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "session_id": thread_id,
            "timestamp": timestamp,
            "thread_source": thread_source,
        },
    }


def token_event(
    timestamp: str,
    total: dict[str, int],
    last: dict[str, int],
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": total,
                "last_token_usage": last,
                "model_context_window": 200_000,
            },
            "rate_limits": {"limit_id": "codex"},
        },
    }


def marker_event(timestamp: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "agent_message", "message": IMPORT_MARKER},
    }


def make_home(tmp_path: Path, *, auth_mode: str = "apikey") -> Path:
    home = tmp_path / "codex-home"
    (home / "sessions" / "2026" / "07" / "25").mkdir(parents=True)
    (home / "auth.json").write_text(
        json.dumps({"auth_mode": auth_mode, "OPENAI_API_KEY": "secret-not-for-output"})
    )
    return home


def write_session(home: Path, name: str, records: list[dict[str, object]]) -> Path:
    path = home / "sessions" / "2026" / "07" / "25" / f"{name}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def all_time_window() -> ScanWindow:
    return ScanWindow(None, NOW, timezone.utc, "UTC", "all time")


def test_counts_only_new_cumulative_states(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    first_total = usage(100, 10, cached=40, reasoning=4)
    second_total = usage(250, 20, cached=160, reasoning=7)
    write_session(
        home,
        "root",
        [
            session_meta("root", "2026-07-25T01:00:00Z"),
            token_event("2026-07-25T01:01:00Z", first_total, first_total),
            token_event("2026-07-25T01:02:00Z", first_total, first_total),
            token_event(
                "2026-07-25T01:03:00Z",
                second_total,
                usage(150, 10, cached=120, reasoning=3),
            ),
        ],
    )
    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.usage.total_tokens == 270
    assert result.usage.cached_input_tokens == 160
    assert result.diagnostics["duplicate_token_snapshots_ignored"] == 1
    assert result.diagnostics["token_events_counted"] == 2


def test_first_session_meta_owns_subagent_file(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "subagent",
        [
            session_meta("child", "2026-07-25T01:00:00Z", thread_source="subagent"),
            session_meta("parent", "2026-07-24T01:00:00Z"),
            token_event("2026-07-25T01:01:00Z", usage(50, 5), usage(50, 5)),
        ],
    )
    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.by_thread_type["subagent"].total_tokens == 55
    assert result.by_thread_type["root"].total_tokens == 0
    assert result.diagnostics["inherited_session_meta_records"] == 1


def test_import_history_is_excluded_but_continuation_is_counted(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    (home / "external_agent_session_imports.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "source_path": "/redacted/source.jsonl",
                        "content_sha256": "abc",
                        "imported_thread_id": "imported",
                        "imported_at": 1_753_401_600,
                    }
                ]
            }
        )
    )
    write_session(
        home,
        "imported",
        [
            session_meta("imported", "2025-07-25T00:00:00Z"),
            marker_event("2025-07-24T23:59:00Z"),
            token_event("2025-07-24T23:58:00Z", usage(80, 8), usage(80, 8)),
            token_event(
                "2025-07-25T00:00:00Z",
                usage(0, 0, total_tokens=1_000),
                usage(0, 0, total_tokens=1_000),
            ),
            token_event(
                "2025-07-25T00:01:00Z",
                usage(200, 10, total_tokens=1_210),
                usage(200, 10),
            ),
        ],
    )
    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.usage.total_tokens == 210
    assert result.diagnostics["import_history_events_excluded"] == 1
    assert result.diagnostics["import_synthetic_events_excluded"] == 1
    assert result.diagnostics["continued_import_threads"] == 1


def test_marker_fallback_excludes_pre_import_history(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "marker-only",
        [
            session_meta("marker-only", "2026-07-25T01:00:00Z"),
            marker_event("2026-07-25T00:59:00Z"),
            token_event("2026-07-25T00:58:00Z", usage(100, 10), usage(100, 10)),
            token_event("2026-07-25T01:01:00Z", usage(150, 15), usage(50, 5)),
        ],
    )
    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.usage.total_tokens == 55
    assert result.diagnostics["import_history_events_excluded"] == 1


def test_exact_event_copies_are_counted_once(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    copied = token_event("2026-07-25T01:01:00Z", usage(40, 4), usage(40, 4))
    write_session(home, "one", [session_meta("one", "2026-07-25T01:00:00Z"), copied])
    write_session(home, "two", [session_meta("two", "2026-07-25T01:00:30Z"), copied])
    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.usage.total_tokens == 44
    assert result.diagnostics["exact_duplicate_events_ignored"] == 1


def test_bounded_window_is_end_exclusive(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    write_session(
        home,
        "window",
        [
            session_meta("window", "2026-07-25T00:00:00Z"),
            token_event("2026-07-25T00:59:00Z", usage(10, 1), usage(10, 1)),
            token_event("2026-07-25T01:30:00Z", usage(30, 3), usage(20, 2)),
            token_event("2026-07-25T02:00:00Z", usage(60, 6), usage(30, 3)),
        ],
    )
    window = ScanWindow(
        datetime(2026, 7, 25, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 25, 2, 0, tzinfo=timezone.utc),
        timezone.utc,
        "UTC",
        "custom range",
    )
    result = scan_codex_usage(home, window, now=NOW)
    assert result.usage.total_tokens == 22


def test_malformed_records_and_counter_reset_are_reported(tmp_path: Path) -> None:
    home = make_home(tmp_path, auth_mode="chatgpt")
    path = write_session(
        home,
        "broken",
        [
            session_meta("broken", "2026-07-25T01:00:00Z"),
            token_event("2026-07-25T01:01:00Z", usage(100, 10), usage(100, 10)),
            token_event("2026-07-25T01:02:00Z", usage(20, 2), usage(20, 2)),
        ],
    )
    with path.open("ab") as handle:
        handle.write(b"not-json\n{unfinished")
    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.usage.total_tokens == 132
    assert result.warnings["malformed_json_lines"] == 1
    assert result.warnings["truncated_tail_lines"] == 1
    assert result.warnings["token_counter_resets"] == 1
    assert result.warnings["current_auth_is_not_api_key"] == 1
