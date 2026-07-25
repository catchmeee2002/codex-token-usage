from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .model import ScanResult, ScanWindow, Usage, cumulative_signature


IMPORT_MARKER = "<EXTERNAL SESSION IMPORTED>"
READ_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class ImportRecord:
    imported_at: datetime | None


@dataclass(frozen=True)
class TokenEvent:
    timestamp: Any
    total_usage: Mapping[str, Any]
    last_usage: Mapping[str, Any]
    model_context_window: Any
    rate_limits: Any
    before_subagent_trigger: bool
    effort: str | None
    model: str | None
    turn_id: str | None


@dataclass
class TurnEvidence:
    start: Any = None
    end: Any = None
    effort: str | None = None
    model: str | None = None


@dataclass
class FileEvidence:
    first_meta: Mapping[str, Any] | None = None
    later_meta_count: int = 0
    import_marker_seen: bool = False
    subagent_trigger_seen: bool = False
    current_turn_id: str | None = None
    current_effort: str | None = None
    current_model: str | None = None
    turns: dict[str, TurnEvidence] = field(default_factory=dict)
    token_events: list[TokenEvent] = field(default_factory=list)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def _event_fingerprint(
    event: TokenEvent,
    total_signature: tuple[int, ...],
    last_signature: tuple[int, ...],
) -> tuple[Any, ...]:
    return (
        event.timestamp,
        total_signature,
        last_signature,
        event.model_context_window,
        _canonical_json(event.rate_limits),
    )


def _consume_object(obj: Any, evidence: FileEvidence) -> None:
    if not isinstance(obj, dict):
        return
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return
    if obj.get("type") == "session_meta":
        if evidence.first_meta is None:
            evidence.first_meta = payload
        else:
            evidence.later_meta_count += 1
        return
    if obj.get("type") == "inter_agent_communication_metadata":
        if payload.get("trigger_turn") is True:
            evidence.subagent_trigger_seen = True
        return
    if obj.get("type") == "turn_context":
        turn_id = payload.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            evidence.current_turn_id = turn_id
        effort = payload.get("effort")
        mode = payload.get("collaboration_mode")
        settings = mode.get("settings") if isinstance(mode, dict) else None
        if not isinstance(settings, dict):
            settings = {}
        configured_effort = settings.get("reasoning_effort")
        configured_model = settings.get("model")
        evidence.current_effort = (
            effort
            if isinstance(effort, str) and effort
            else configured_effort if isinstance(configured_effort, str) else None
        )
        model = payload.get("model")
        evidence.current_model = (
            model
            if isinstance(model, str) and model
            else configured_model if isinstance(configured_model, str) else None
        )
        if evidence.current_turn_id:
            turn = evidence.turns.setdefault(evidence.current_turn_id, TurnEvidence())
            turn.effort = evidence.current_effort
            turn.model = evidence.current_model
        return
    if obj.get("type") != "event_msg":
        return
    if payload.get("type") == "task_started":
        turn_id = payload.get("turn_id")
        evidence.current_turn_id = turn_id if isinstance(turn_id, str) and turn_id else None
        if evidence.current_turn_id:
            turn = evidence.turns.setdefault(evidence.current_turn_id, TurnEvidence())
            turn.start = obj.get("timestamp")
            turn.effort = evidence.current_effort
            turn.model = evidence.current_model
        return
    if payload.get("type") == "task_complete":
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            turn_id = evidence.current_turn_id
        if turn_id:
            turn = evidence.turns.setdefault(turn_id, TurnEvidence())
            turn.end = obj.get("timestamp")
        return
    if payload.get("type") == "agent_message":
        if payload.get("message") == IMPORT_MARKER:
            evidence.import_marker_seen = True
        return
    if payload.get("type") != "token_count":
        return
    info = payload.get("info")
    if not isinstance(info, dict):
        return
    total_usage = info.get("total_token_usage")
    last_usage = info.get("last_token_usage")
    if not isinstance(total_usage, dict) or not isinstance(last_usage, dict):
        return
    evidence.token_events.append(
        TokenEvent(
            timestamp=obj.get("timestamp"),
            total_usage=total_usage,
            last_usage=last_usage,
            model_context_window=info.get("model_context_window"),
            rate_limits=payload.get("rate_limits"),
            before_subagent_trigger=not evidence.subagent_trigger_seen,
            effort=evidence.current_effort,
            model=evidence.current_model,
            turn_id=evidence.current_turn_id,
        )
    )


def _read_file_evidence(path: Path, result: ScanResult) -> FileEvidence | None:
    evidence = FileEvidence()
    try:
        before = path.stat()
        remaining = before.st_size
        buffer = b""
        with path.open("rb") as handle:
            while remaining > 0:
                chunk = handle.read(min(READ_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                buffer += chunk
                while True:
                    newline = buffer.find(b"\n")
                    if newline < 0:
                        break
                    raw_line = buffer[:newline]
                    buffer = buffer[newline + 1 :]
                    if not raw_line.strip():
                        continue
                    try:
                        _consume_object(json.loads(raw_line), evidence)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        result.warn("malformed_json_lines")
        if buffer.strip():
            try:
                _consume_object(json.loads(buffer), evidence)
            except (json.JSONDecodeError, UnicodeDecodeError):
                result.warn("truncated_tail_lines")
        after = path.stat()
        if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
            result.warn("files_changed_during_scan")
    except OSError:
        result.warn("unreadable_session_files")
        return None
    return evidence


def _load_auth_mode(codex_home: Path, result: ScanResult) -> str | None:
    try:
        payload = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        result.warn("auth_status_unknown")
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        result.warn("auth_status_unknown")
        return None
    mode = payload.get("auth_mode") if isinstance(payload, dict) else None
    if not isinstance(mode, str) or not mode:
        result.warn("auth_status_unknown")
        return None
    if mode != "apikey":
        result.warn("current_auth_is_not_api_key")
    return mode


def _load_import_ledger(codex_home: Path, result: ScanResult) -> dict[str, ImportRecord]:
    path = codex_home / "external_agent_session_imports.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result.bump_diagnostic("import_ledger_missing")
        return {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        result.warn("invalid_import_ledger")
        return {}
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        result.warn("invalid_import_ledger")
        return {}

    imported: dict[str, ImportRecord] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("imported_thread_id"), str):
            result.warn("invalid_import_ledger_records")
            continue
        imported_at_raw = record.get("imported_at")
        imported_at = None
        if isinstance(imported_at_raw, int) and not isinstance(imported_at_raw, bool):
            try:
                imported_at = datetime.fromtimestamp(imported_at_raw, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                result.warn("invalid_import_ledger_records")
        elif imported_at_raw is not None:
            result.warn("invalid_import_ledger_records")
        imported[record["imported_thread_id"]] = ImportRecord(imported_at=imported_at)
    result.bump_diagnostic("import_ledger_records", len(imported))
    return imported


def scan_codex_usage(codex_home: Path, window: ScanWindow, *, now: datetime) -> ScanResult:
    result = ScanResult(
        generated_at=now.astimezone(timezone.utc),
        window=window,
        auth_mode=None,
    )
    result.auth_mode = _load_auth_mode(codex_home, result)
    imported_records = _load_import_ledger(codex_home, result)

    sessions_root = codex_home / "sessions"
    if not sessions_root.is_dir():
        result.warn("sessions_directory_missing")
        return result

    seen_fingerprints: set[tuple[Any, ...]] = set()
    actual_threads: set[str] = set()
    imported_threads_seen: set[str] = set()
    continued_import_threads: set[str] = set()

    for path in sorted(sessions_root.rglob("*.jsonl")):
        result.bump_diagnostic("session_files_scanned")
        evidence = _read_file_evidence(path, result)
        if evidence is None:
            continue
        if evidence.later_meta_count:
            result.bump_diagnostic("inherited_session_meta_records", evidence.later_meta_count)
        if evidence.first_meta is None:
            result.warn("session_files_without_metadata")
            continue
        if evidence.token_events:
            result.bump_diagnostic("session_files_with_token_events")

        meta = evidence.first_meta
        thread_id = meta.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            result.warn("session_files_without_thread_id")
            continue
        thread_type = "subagent" if meta.get("thread_source") == "subagent" else "root"
        if thread_type == "subagent" and evidence.token_events and not evidence.subagent_trigger_seen:
            result.warn("subagent_history_boundary_missing")
        thread_started_at = _parse_timestamp(meta.get("timestamp"))
        if thread_started_at is None:
            result.warn("invalid_session_start_timestamps")

        ledger_record = imported_records.get(thread_id)
        ledger_imported = ledger_record is not None
        marker_imported = evidence.import_marker_seen
        if ledger_imported != marker_imported:
            result.warn("import_evidence_mismatches")
        is_imported = ledger_imported or marker_imported
        import_boundary = (
            ledger_record.imported_at if ledger_record and ledger_record.imported_at else thread_started_at
        )
        if is_imported:
            imported_threads_seen.add(thread_id)

        previous_total: tuple[int, ...] | None = None
        thread_has_counted_usage = False
        for event in evidence.token_events:
            result.bump_diagnostic("token_events_seen")
            if (
                thread_type == "subagent"
                and evidence.subagent_trigger_seen
                and event.before_subagent_trigger
            ):
                result.bump_diagnostic("subagent_history_events_excluded")
                continue
            try:
                total_signature = cumulative_signature(event.total_usage)
                last_signature = cumulative_signature(event.last_usage)
                usage = Usage.from_mapping(event.last_usage)
                usage.validate()
            except ValueError:
                result.warn("invalid_token_usage_events")
                continue

            timestamp = _parse_timestamp(event.timestamp)
            if is_imported and import_boundary is not None:
                if timestamp is None:
                    if usage.input_tokens or usage.output_tokens:
                        result.warn("ambiguous_import_events")
                    continue
                if timestamp < import_boundary:
                    result.bump_diagnostic("import_history_events_excluded")
                    continue

            if previous_total == total_signature:
                result.bump_diagnostic("duplicate_token_snapshots_ignored")
                continue
            if previous_total is not None and any(
                current < previous for current, previous in zip(total_signature, previous_total)
            ):
                result.warn("token_counter_resets")
            previous_total = total_signature

            fingerprint = _event_fingerprint(event, total_signature, last_signature)
            if fingerprint in seen_fingerprints:
                result.bump_diagnostic("exact_duplicate_events_ignored")
                continue
            seen_fingerprints.add(fingerprint)

            if usage.input_tokens == 0 and usage.output_tokens == 0:
                if is_imported and total_signature[-1] > 0:
                    result.bump_diagnostic("import_synthetic_events_excluded")
                else:
                    result.bump_diagnostic("zero_billable_usage_events_ignored")
                continue

            if timestamp is None:
                result.warn("invalid_token_event_timestamps")
                if window.start is not None:
                    result.bump_diagnostic("untimed_events_outside_bounded_window")
                    continue
                day = None
            else:
                if not window.includes(timestamp):
                    result.bump_diagnostic("token_events_outside_window")
                    continue
                day = timestamp.astimezone(window.timezone).date().isoformat()

            result.add_usage(usage, thread_type, day)
            turn_key = f"{thread_id}:{event.turn_id}" if event.turn_id else None
            result.add_effort_usage(
                usage,
                effort=event.effort,
                model=event.model,
                turn_key=turn_key,
            )
            result.bump_diagnostic("token_events_counted")
            actual_threads.add(thread_id)
            thread_has_counted_usage = True

        if is_imported and thread_has_counted_usage:
            continued_import_threads.add(thread_id)

        for turn_id, turn in evidence.turns.items():
            start = _parse_timestamp(turn.start)
            end = _parse_timestamp(turn.end)
            if start is None or end is None or end <= start:
                continue
            clipped_start = max(start, window.start) if window.start is not None else start
            clipped_end = min(end, window.end)
            if clipped_end <= clipped_start:
                continue
            result.add_effort_turn_duration(
                effort=turn.effort,
                turn_key=f"{thread_id}:{turn_id}",
                seconds=(clipped_end - clipped_start).total_seconds(),
            )

    result.bump_diagnostic("actual_threads", len(actual_threads))
    result.bump_diagnostic("imported_threads_seen", len(imported_threads_seen))
    result.bump_diagnostic("continued_import_threads", len(continued_import_threads))
    return result
