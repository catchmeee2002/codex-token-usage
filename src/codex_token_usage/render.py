from __future__ import annotations

from datetime import datetime

from .model import ScanResult, Usage


WARNING_TEXT = {
    "ambiguous_import_events": "imported events had no usable timestamp and were excluded",
    "auth_status_unknown": "current Codex authentication mode could not be determined",
    "current_auth_is_not_api_key": "current Codex authentication mode is not API key",
    "files_changed_during_scan": "session files changed while their stable prefix was scanned",
    "import_evidence_mismatches": "the import ledger and imported-session marker disagreed",
    "invalid_import_ledger": "the imported-session ledger could not be parsed",
    "invalid_import_ledger_records": "invalid records were skipped in the imported-session ledger",
    "invalid_session_start_timestamps": "session start timestamps could not be parsed",
    "invalid_token_event_timestamps": "token events had invalid timestamps",
    "invalid_token_usage_events": "token events contained invalid counters and were skipped",
    "malformed_json_lines": "malformed non-tail JSONL records were skipped",
    "session_files_without_metadata": "session files without session metadata were skipped",
    "session_files_without_thread_id": "session files without a thread ID were skipped",
    "sessions_directory_missing": "the Codex sessions directory does not exist",
    "token_counter_resets": "cumulative token counters decreased; a new segment was counted",
    "truncated_tail_lines": "unfinished final JSONL records were ignored",
    "unreadable_session_files": "session files could not be read",
}


def _number(value: int) -> str:
    return f"{value:,}"


def _local_time(value: datetime, result: ScanResult) -> str:
    return value.astimezone(result.window.timezone).isoformat(timespec="seconds")


def _usage_lines(usage: Usage, indent: str = "") -> list[str]:
    lines = [
        f"{indent}Total tokens:           {_number(usage.total_tokens)}",
        f"{indent}Input tokens:           {_number(usage.input_tokens)}",
        f"{indent}  Cached input:         {_number(usage.cached_input_tokens)}",
        f"{indent}  Uncached input:       {_number(usage.uncached_input_tokens)}",
    ]
    if usage.cache_write_input_tokens:
        lines.append(f"{indent}  Cache-write input:    {_number(usage.cache_write_input_tokens)}")
    lines.extend(
        [
            f"{indent}Output tokens:          {_number(usage.output_tokens)}",
            f"{indent}  Reasoning output:     {_number(usage.reasoning_output_tokens)}",
        ]
    )
    return lines


def _daily_table(result: ScanResult) -> list[str]:
    if not result.daily:
        return ["No timed token events matched the selected window."]
    headers = ("Date", "Total", "Input", "Cached", "Output", "Reasoning")
    rows = [
        (
            day,
            _number(usage.total_tokens),
            _number(usage.input_tokens),
            _number(usage.cached_input_tokens),
            _number(usage.output_tokens),
            _number(usage.reasoning_output_tokens),
        )
        for day, usage in sorted(result.daily.items())
    ]
    widths = [max(len(headers[index]), *(len(row[index]) for row in rows)) for index in range(6)]

    def format_row(row: tuple[str, ...]) -> str:
        return "  ".join(
            value.ljust(widths[index]) if index == 0 else value.rjust(widths[index])
            for index, value in enumerate(row)
        )

    return [format_row(headers), format_row(tuple("-" * width for width in widths)), *map(format_row, rows)]


def render_human(result: ScanResult, *, include_daily: bool) -> str:
    if result.window.start is None:
        window_text = f"all recorded time through {_local_time(result.window.end, result)}"
    else:
        window_text = (
            f"{_local_time(result.window.start, result)} through "
            f"{_local_time(result.window.end, result)} (end exclusive)"
        )
    auth_mode = result.auth_mode or "unknown"

    lines = [
        "Codex token usage",
        f"Window: {result.window.label}; {window_text}",
        f"Current auth mode: {auth_mode}",
        "Historical session logs do not identify the API key that was used.",
        "",
        *_usage_lines(result.usage),
        "",
        "By thread type",
    ]
    for key in ("root", "subagent", "unknown"):
        usage = result.by_thread_type.get(key, Usage())
        if usage.total_tokens or key != "unknown":
            lines.append(f"  {key}: {_number(usage.total_tokens)} tokens")

    diagnostics = result.diagnostics
    lines.extend(
        [
            "",
            "Import handling",
            f"  Ledger records:              {_number(diagnostics.get('import_ledger_records', 0))}",
            f"  Imported threads seen:       {_number(diagnostics.get('imported_threads_seen', 0))}",
            f"  Imported history excluded:   {_number(diagnostics.get('import_history_events_excluded', 0))} events",
            f"  Synthetic imports excluded:  {_number(diagnostics.get('import_synthetic_events_excluded', 0))} events",
            f"  Continued imported threads:  {_number(diagnostics.get('continued_import_threads', 0))}",
            "",
            "Integrity",
            f"  Session files scanned:       {_number(diagnostics.get('session_files_scanned', 0))}",
            f"  Token events counted:        {_number(diagnostics.get('token_events_counted', 0))}",
            f"  Duplicate snapshots ignored: {_number(diagnostics.get('duplicate_token_snapshots_ignored', 0))}",
            f"  Exact duplicates ignored:    {_number(diagnostics.get('exact_duplicate_events_ignored', 0))}",
        ]
    )

    if include_daily:
        lines.extend(["", "Daily", *_daily_table(result)])
    if result.warnings:
        lines.extend(["", "Warnings"])
        for code, count in sorted(result.warnings.items()):
            message = WARNING_TEXT.get(code, code.replace("_", " "))
            lines.append(f"  {code} ({count}): {message}")
    return "\n".join(lines) + "\n"
