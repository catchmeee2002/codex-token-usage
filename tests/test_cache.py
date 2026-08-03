from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from codex_token_usage.cache import CACHE_SCHEMA_VERSION, cache_path
from codex_token_usage.cli import build_parser, main
from codex_token_usage.model import ScanResult
from codex_token_usage.scanner import scan_codex_usage
from codex_token_usage.timeparse import build_window
from codex_token_usage.tui import TokenUsageTui

from test_scanner import make_home, session_meta, token_event, usage, write_session


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def all_time_window():
    return build_window(
        now=NOW,
        timezone_name="UTC",
        all_time=True,
        since=None,
        from_value=None,
        to_value=None,
    )


def make_session(home, name="root"):
    return write_session(
        home,
        name,
        [
            session_meta(name, "2026-07-25T01:00:00Z"),
            token_event("2026-07-25T01:01:00Z", usage(100, 10), usage(100, 10)),
        ],
    )


def test_second_scan_reuses_cached_evidence_without_changing_totals(tmp_path) -> None:
    home = make_home(tmp_path)
    make_session(home)

    first = scan_codex_usage(home, all_time_window(), now=NOW)
    second = scan_codex_usage(home, all_time_window(), now=NOW)

    assert first.usage.as_dict() == second.usage.as_dict()
    assert first.warnings == second.warnings
    assert first.diagnostics["session_files_fully_parsed"] == 1
    assert second.diagnostics["session_files_cache_hits"] == 1
    assert second.diagnostics["session_files_fully_parsed"] == 0
    assert cache_path(home).is_file()


def test_append_only_file_reads_incrementally_and_updates_usage(tmp_path) -> None:
    home = make_home(tmp_path)
    path = make_session(home)
    scan_codex_usage(home, all_time_window(), now=NOW)

    event = token_event("2026-07-25T01:02:00Z", usage(150, 15), usage(50, 5))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")

    result = scan_codex_usage(home, all_time_window(), now=NOW)

    assert result.usage.total_tokens == 165
    assert result.diagnostics["session_files_incrementally_parsed"] == 1
    assert result.diagnostics["session_files_fully_parsed"] == 0


def test_incomplete_tail_is_retried_when_append_completes_it(tmp_path) -> None:
    home = make_home(tmp_path)
    path = make_session(home)
    encoded = json.dumps(
        token_event("2026-07-25T01:02:00Z", usage(150, 15), usage(50, 5))
    )
    midpoint = len(encoded) // 2
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded[:midpoint])

    first = scan_codex_usage(home, all_time_window(), now=NOW)
    assert first.warnings["truncated_tail_lines"] == 1

    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded[midpoint:] + "\n")
    second = scan_codex_usage(home, all_time_window(), now=NOW)

    assert second.usage.total_tokens == 165
    assert "truncated_tail_lines" not in second.warnings
    assert second.diagnostics["session_files_incrementally_parsed"] == 1


def test_replaced_file_is_fully_reparsed(tmp_path) -> None:
    home = make_home(tmp_path)
    path = make_session(home)
    scan_codex_usage(home, all_time_window(), now=NOW)

    path.write_text(
        "".join(
            json.dumps(record) + "\n"
            for record in [
                session_meta("replacement", "2026-07-25T02:00:00Z"),
                token_event("2026-07-25T02:01:00Z", usage(20, 2), usage(20, 2)),
            ]
        ),
        encoding="utf-8",
    )
    result = scan_codex_usage(home, all_time_window(), now=NOW)

    assert result.usage.total_tokens == 22
    assert result.diagnostics["session_files_fully_parsed"] == 1
    assert result.diagnostics["session_files_cache_hits"] == 0


def test_equal_size_rewrite_is_not_treated_as_append(tmp_path) -> None:
    home = make_home(tmp_path)
    path = make_session(home)
    original_size = path.stat().st_size
    scan_codex_usage(home, all_time_window(), now=NOW)

    path.write_text(
        "".join(
            json.dumps(record) + "\n"
            for record in [
                session_meta("root", "2026-07-25T01:00:00Z"),
                token_event("2026-07-25T01:01:00Z", usage(200, 20), usage(200, 20)),
            ]
        ),
        encoding="utf-8",
    )
    assert path.stat().st_size == original_size

    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.usage.total_tokens == 220
    assert result.diagnostics["session_files_fully_parsed"] == 1


def test_deleted_file_is_removed_from_cache_and_totals(tmp_path) -> None:
    home = make_home(tmp_path)
    path = make_session(home)
    scan_codex_usage(home, all_time_window(), now=NOW)
    path.unlink()

    result = scan_codex_usage(home, all_time_window(), now=NOW)

    assert result.usage.total_tokens == 0
    assert result.diagnostics["session_files_removed_from_cache"] == 1


def test_content_warnings_are_replayed_on_cache_hits(tmp_path) -> None:
    home = make_home(tmp_path)
    path = make_session(home)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")

    first = scan_codex_usage(home, all_time_window(), now=NOW)
    second = scan_codex_usage(home, all_time_window(), now=NOW)

    assert first.warnings["malformed_json_lines"] == 1
    assert second.warnings["malformed_json_lines"] == 1
    assert second.diagnostics["session_files_cache_hits"] == 1


def test_import_ledger_is_reloaded_when_file_evidence_is_cached(tmp_path) -> None:
    home = make_home(tmp_path)
    make_session(home, "imported")
    first = scan_codex_usage(home, all_time_window(), now=NOW)
    assert first.diagnostics["import_ledger_missing"] == 1

    (home / "external_agent_session_imports.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "imported_thread_id": "imported",
                        "imported_at": 1_753_401_600,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    second = scan_codex_usage(home, all_time_window(), now=NOW)

    assert second.diagnostics["import_ledger_records"] == 1
    assert second.diagnostics["session_files_cache_hits"] == 1
    assert second.warnings["import_evidence_mismatches"] == 1


def test_corrupt_or_outdated_cache_is_disposable(tmp_path) -> None:
    home = make_home(tmp_path)
    make_session(home)
    scan_codex_usage(home, all_time_window(), now=NOW)
    path = cache_path(home)

    path.write_bytes(b"not-a-sqlite-database")
    recovered = scan_codex_usage(home, all_time_window(), now=NOW)
    assert recovered.usage.total_tokens == 110
    assert recovered.diagnostics["session_files_fully_parsed"] == 1

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
            (str(CACHE_SCHEMA_VERSION + 1),),
        )
    rebuilt = scan_codex_usage(home, all_time_window(), now=NOW)
    assert rebuilt.usage.total_tokens == 110
    assert rebuilt.diagnostics["session_files_fully_parsed"] == 1


def test_missing_committed_chunk_forces_full_reparse(tmp_path) -> None:
    home = make_home(tmp_path)
    make_session(home)
    scan_codex_usage(home, all_time_window(), now=NOW)
    with sqlite3.connect(cache_path(home)) as connection:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("DELETE FROM chunks WHERE sequence = 0")

    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.usage.total_tokens == 110
    assert result.diagnostics["session_files_fully_parsed"] == 1


def test_invalid_compressed_chunk_forces_full_reparse(tmp_path) -> None:
    home = make_home(tmp_path)
    make_session(home)
    scan_codex_usage(home, all_time_window(), now=NOW)
    with sqlite3.connect(cache_path(home)) as connection:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("UPDATE chunks SET evidence_blob = ?", (b"invalid-zlib",))

    result = scan_codex_usage(home, all_time_window(), now=NOW)
    assert result.usage.total_tokens == 110
    assert result.diagnostics["session_files_fully_parsed"] == 1


def test_cache_failure_falls_back_to_full_scan(tmp_path, monkeypatch) -> None:
    home = make_home(tmp_path)
    make_session(home)

    def fail(_self):
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr("codex_token_usage.scanner.SessionEvidenceCache.__enter__", fail)
    result = scan_codex_usage(home, all_time_window(), now=NOW)

    assert result.usage.total_tokens == 110
    assert result.diagnostics["scan_cache_fallbacks"] == 1
    assert result.diagnostics["session_files_fully_parsed"] == 1


def test_no_cache_mode_does_not_create_database(tmp_path) -> None:
    home = make_home(tmp_path)
    make_session(home)

    result = scan_codex_usage(home, all_time_window(), now=NOW, cache_mode="disabled")

    assert result.usage.total_tokens == 110
    assert result.diagnostics["scan_cache_enabled"] == 0
    assert not cache_path(home).exists()


def test_cli_cache_flags_are_mutually_exclusive_and_rebuild_is_reported(tmp_path) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--rebuild-cache", "--no-cache"])

    home = make_home(tmp_path)
    make_session(home)
    stdout = io.StringIO()
    code = main(
        ["--codex-home", str(home), "--all", "--rebuild-cache"],
        now=NOW,
        stdout=stdout,
    )
    assert code == 0
    assert "完整解析文件：       1" in stdout.getvalue()


def test_tui_lowercase_refresh_and_uppercase_rebuild_use_distinct_modes() -> None:
    class Screen:
        def __init__(self):
            self.keys = iter((ord("r"), ord("R"), ord("q")))

        def getch(self):
            return next(self.keys)

    tui = object.__new__(TokenUsageTui)
    tui.screen = Screen()
    tui.active_choice = 0
    tui.cache_mode = "use"
    calls = []
    tui._draw = lambda: None
    tui._load = lambda index, **kwargs: calls.append((index, kwargs))

    assert tui.run() == 0
    assert calls == [
        (0, {}),
        (0, {"prompt_custom": False}),
        (0, {"prompt_custom": False, "cache_mode": "rebuild"}),
    ]
