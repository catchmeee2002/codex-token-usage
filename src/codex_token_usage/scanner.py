from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .cache import CacheMode, CachedFile, SessionEvidenceCache, cache_path
from .model import ScanResult, ScanWindow, Usage, cumulative_signature


IMPORT_MARKER = "<EXTERNAL SESSION IMPORTED>"
READ_CHUNK_SIZE = 64 * 1024
BOUNDARY_HASH_SIZE = 4 * 1024


@dataclass(frozen=True)
class ImportRecord:
    imported_at: datetime | None


@dataclass(frozen=True)
class TokenEvent:
    timestamp: Any
    total_signature: tuple[int, ...]
    usage_values: tuple[int, ...]
    fingerprint: str
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
    content_warnings: dict[str, int] = field(default_factory=dict)

    def warn(self, code: str, amount: int = 1) -> None:
        self.content_warnings[code] = self.content_warnings.get(code, 0) + amount


@dataclass(frozen=True)
class ReadEvidence:
    evidence: FileEvidence
    device: int
    inode: int
    source_size: int
    source_mtime_ns: int
    parsed_offset: int
    boundary_hash: str


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
    timestamp: Any,
    total_signature: tuple[int, ...],
    last_signature: tuple[int, ...],
    model_context_window: Any,
    rate_limits: Any,
) -> str:
    payload = _canonical_json(
        (
            timestamp,
            total_signature,
            last_signature,
            model_context_window,
            _canonical_json(rate_limits),
        )
    )
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def _consume_object(obj: Any, evidence: FileEvidence) -> None:
    if not isinstance(obj, dict):
        return
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return
    if obj.get("type") == "session_meta":
        if evidence.first_meta is None:
            evidence.first_meta = {
                "id": payload.get("id"),
                "timestamp": payload.get("timestamp"),
                "thread_source": payload.get("thread_source"),
            }
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
    try:
        total_signature = cumulative_signature(total_usage)
        last_signature = cumulative_signature(last_usage)
        usage = Usage.from_mapping(last_usage)
        usage.validate()
    except ValueError:
        evidence.warn("invalid_token_usage_events")
        return
    evidence.token_events.append(
        TokenEvent(
            timestamp=obj.get("timestamp"),
            total_signature=total_signature,
            usage_values=tuple(getattr(usage, name) for name in (
                "input_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )),
            fingerprint=_event_fingerprint(
                obj.get("timestamp"),
                total_signature,
                last_signature,
                info.get("model_context_window"),
                payload.get("rate_limits"),
            ),
            before_subagent_trigger=not evidence.subagent_trigger_seen,
            effort=evidence.current_effort,
            model=evidence.current_model,
            turn_id=evidence.current_turn_id,
        )
    )


def _boundary_hash(path: Path, offset: int) -> str:
    start = max(0, offset - BOUNDARY_HASH_SIZE)
    with path.open("rb") as handle:
        handle.seek(start)
        payload = handle.read(offset - start)
    return hashlib.sha256(payload).hexdigest()


def _evidence_json(evidence: FileEvidence) -> str:
    payload = {
        "m": evidence.first_meta,
        "lm": evidence.later_meta_count,
        "im": evidence.import_marker_seen,
        "st": evidence.subagent_trigger_seen,
        "cs": [evidence.current_turn_id, evidence.current_effort, evidence.current_model],
        "tw": [
            [turn_id, turn.start, turn.end, turn.effort, turn.model]
            for turn_id, turn in evidence.turns.items()
        ],
        "ev": [
            [
                event.timestamp,
                list(event.total_signature),
                [
                    *event.usage_values,
                ],
                event.fingerprint,
                event.before_subagent_trigger,
                event.effort,
                event.model,
                event.turn_id,
            ]
            for event in evidence.token_events
        ],
        "w": evidence.content_warnings,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _evidence_from_json(raw: str) -> FileEvidence:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("cached evidence is not an object")
    current = payload.get("cs", [None, None, None])
    evidence = FileEvidence(
        first_meta=payload.get("m"),
        later_meta_count=int(payload.get("lm", 0)),
        import_marker_seen=bool(payload.get("im", False)),
        subagent_trigger_seen=bool(payload.get("st", False)),
        current_turn_id=current[0],
        current_effort=current[1],
        current_model=current[2],
        content_warnings={
            str(key): int(value) for key, value in dict(payload.get("w", {})).items()
        },
    )
    for item in payload.get("tw", []):
        turn_id, start, end, effort, model = item
        evidence.turns[str(turn_id)] = TurnEvidence(start, end, effort, model)
    for item in payload.get("ev", []):
        timestamp, total, usage_values, fingerprint, before, effort, model, turn_id = item
        evidence.token_events.append(
            TokenEvent(
                timestamp=timestamp,
                total_signature=tuple(int(value) for value in total),
                usage_values=tuple(int(value) for value in usage_values),
                fingerprint=str(fingerprint),
                before_subagent_trigger=bool(before),
                effort=effort,
                model=model,
                turn_id=turn_id,
            )
        )
    return evidence


def _replay_content_warnings(evidence: FileEvidence, result: ScanResult) -> None:
    for code, count in evidence.content_warnings.items():
        result.warn(code, count)


def _read_file_evidence(
    path: Path,
    result: ScanResult,
    *,
    evidence: FileEvidence | None = None,
    start_offset: int = 0,
) -> ReadEvidence | None:
    evidence = evidence or FileEvidence()
    evidence.content_warnings.pop("truncated_tail_lines", None)
    try:
        before = path.stat()
        if start_offset < 0 or start_offset > before.st_size:
            raise OSError("invalid cached file offset")
        remaining = before.st_size - start_offset
        buffer = b""
        buffer_start = start_offset
        with path.open("rb") as handle:
            handle.seek(start_offset)
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
                    buffer_start += newline + 1
                    if not raw_line.strip():
                        continue
                    try:
                        _consume_object(json.loads(raw_line), evidence)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        evidence.warn("malformed_json_lines")
        read_end = before.st_size - remaining
        parsed_offset = read_end
        if buffer.strip():
            try:
                _consume_object(json.loads(buffer), evidence)
            except (json.JSONDecodeError, UnicodeDecodeError):
                evidence.warn("truncated_tail_lines")
                parsed_offset = buffer_start
        after = path.stat()
        if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
            result.warn("files_changed_during_scan")
        boundary_hash = _boundary_hash(path, parsed_offset)
    except OSError:
        result.warn("unreadable_session_files")
        return None
    return ReadEvidence(
        evidence=evidence,
        device=int(getattr(before, "st_dev", 0)),
        inode=int(getattr(before, "st_ino", 0)),
        source_size=before.st_size,
        source_mtime_ns=before.st_mtime_ns,
        parsed_offset=parsed_offset,
        boundary_hash=boundary_hash,
    )


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


_CACHE_DIAGNOSTICS = (
    "scan_cache_enabled",
    "session_files_cache_hits",
    "session_files_incrementally_parsed",
    "session_files_fully_parsed",
    "session_files_removed_from_cache",
    "scan_cache_rebuilt",
    "scan_cache_fallbacks",
)


def _initialize_cache_diagnostics(result: ScanResult, *, enabled: bool) -> None:
    for code in _CACHE_DIAGNOSTICS:
        result.bump_diagnostic(code, 0)
    result.diagnostics["scan_cache_enabled"] = int(enabled)


def _cache_record(path: str, read: ReadEvidence, *, chunk_count: int) -> CachedFile:
    return CachedFile(
        path=path,
        device=read.device,
        inode=read.inode,
        source_size=read.source_size,
        source_mtime_ns=read.source_mtime_ns,
        parsed_offset=read.parsed_offset,
        boundary_hash=read.boundary_hash,
        chunk_count=chunk_count,
    )


def _incremental_seed(evidence: FileEvidence) -> FileEvidence:
    return FileEvidence(
        first_meta=evidence.first_meta,
        import_marker_seen=evidence.import_marker_seen,
        subagent_trigger_seen=evidence.subagent_trigger_seen,
        current_turn_id=evidence.current_turn_id,
        current_effort=evidence.current_effort,
        current_model=evidence.current_model,
    )


def _merge_evidence(base: FileEvidence, delta: FileEvidence) -> FileEvidence:
    if base.first_meta is None:
        base.first_meta = delta.first_meta
    base.later_meta_count += delta.later_meta_count
    if delta.import_marker_seen:
        base.import_marker_seen = True
    base.subagent_trigger_seen = delta.subagent_trigger_seen
    base.current_turn_id = delta.current_turn_id
    base.current_effort = delta.current_effort
    base.current_model = delta.current_model
    for turn_id, incoming in delta.turns.items():
        turn = base.turns.setdefault(turn_id, TurnEvidence())
        if incoming.start is not None:
            turn.start = incoming.start
        if incoming.end is not None:
            turn.end = incoming.end
        if incoming.effort is not None:
            turn.effort = incoming.effort
        if incoming.model is not None:
            turn.model = incoming.model
    base.token_events.extend(delta.token_events)
    base.content_warnings.pop("truncated_tail_lines", None)
    for code, count in delta.content_warnings.items():
        base.content_warnings[code] = base.content_warnings.get(code, 0) + count
    return base


def _load_cached_evidence(
    chunks_by_path: dict[str, list[tuple[int, str]]],
    record: CachedFile,
) -> FileEvidence:
    chunks = chunks_by_path.get(record.path, [])
    if record.chunk_count <= 0:
        raise ValueError("cached file has no committed evidence chunks")
    expected_sequences = list(range(record.chunk_count))
    selected = [(sequence, raw) for sequence, raw in chunks if sequence < record.chunk_count]
    if [sequence for sequence, _raw in selected] != expected_sequences:
        raise ValueError("cached file has no evidence chunks")
    evidence = _evidence_from_json(selected[0][1])
    for _sequence, raw in selected[1:]:
        evidence = _merge_evidence(evidence, _evidence_from_json(raw))
    return evidence


def _same_identity(record: CachedFile, stat_result: os.stat_result) -> bool:
    device = int(getattr(stat_result, "st_dev", 0))
    inode = int(getattr(stat_result, "st_ino", 0))
    if record.device and device and record.device != device:
        return False
    if record.inode and inode and record.inode != inode:
        return False
    return True


def _collect_without_cache(
    paths: list[Path],
    result: ScanResult,
) -> list[FileEvidence]:
    evidence_items: list[FileEvidence] = []
    for path in paths:
        result.bump_diagnostic("session_files_scanned")
        read = _read_file_evidence(path, result)
        if read is None:
            continue
        result.bump_diagnostic("session_files_fully_parsed")
        _replay_content_warnings(read.evidence, result)
        evidence_items.append(read.evidence)
    return evidence_items


def _collect_with_cache(
    sessions_root: Path,
    paths: list[Path],
    result: ScanResult,
    *,
    mode: CacheMode,
) -> list[FileEvidence]:
    evidence_items: list[FileEvidence] = []
    with SessionEvidenceCache(cache_path(sessions_root.parent)) as cache:
        if mode == "rebuild":
            cache.clear()
            result.bump_diagnostic("scan_cache_rebuilt")
        records = cache.records()
        chunks_by_path = cache.all_evidence_chunks()
        current_paths: set[str] = set()
        for path in paths:
            result.bump_diagnostic("session_files_scanned")
            relative = path.relative_to(sessions_root).as_posix()
            current_paths.add(relative)
            record = records.get(relative)
            try:
                before = path.stat()
            except OSError:
                result.warn("unreadable_session_files")
                continue

            evidence: FileEvidence | None = None
            if mode == "use" and record is not None and _same_identity(record, before):
                exact_match = (
                    record.source_size == before.st_size
                    and record.source_mtime_ns == before.st_mtime_ns
                )
                if exact_match:
                    try:
                        evidence = _load_cached_evidence(chunks_by_path, record)
                        after = path.stat()
                    except (OSError, TypeError, ValueError, json.JSONDecodeError, IndexError):
                        evidence = None
                    else:
                        if (
                            after.st_size != before.st_size
                            or after.st_mtime_ns != before.st_mtime_ns
                        ):
                            result.warn("files_changed_during_scan")
                        result.bump_diagnostic("session_files_cache_hits")
                elif before.st_size > record.source_size:
                    try:
                        boundary_matches = (
                            _boundary_hash(path, record.parsed_offset) == record.boundary_hash
                        )
                        if boundary_matches:
                            cached_evidence = _load_cached_evidence(chunks_by_path, record)
                            delta_seed = _incremental_seed(cached_evidence)
                            read = _read_file_evidence(
                                path,
                                result,
                                evidence=delta_seed,
                                start_offset=record.parsed_offset,
                            )
                        else:
                            read = None
                    except (OSError, TypeError, ValueError, json.JSONDecodeError, IndexError):
                        read = None
                    if read is not None:
                        evidence = _merge_evidence(cached_evidence, read.evidence)
                        cache.append_evidence(
                            relative,
                            record.chunk_count,
                            _evidence_json(read.evidence),
                        )
                        cache.upsert(
                            _cache_record(
                                relative,
                                read,
                                chunk_count=record.chunk_count + 1,
                            )
                        )
                        result.bump_diagnostic("session_files_incrementally_parsed")

            if evidence is None:
                read = _read_file_evidence(path, result)
                if read is None:
                    continue
                evidence = read.evidence
                cache.upsert(_cache_record(relative, read, chunk_count=0))
                cache.replace_evidence(relative, _evidence_json(read.evidence))
                cache.upsert(_cache_record(relative, read, chunk_count=1))
                result.bump_diagnostic("session_files_fully_parsed")

            _replay_content_warnings(evidence, result)
            evidence_items.append(evidence)

        removed = cache.remove_missing(current_paths)
        result.bump_diagnostic("session_files_removed_from_cache", removed)
    return evidence_items


def _collect_file_evidence(
    codex_home: Path,
    sessions_root: Path,
    result: ScanResult,
    *,
    cache_mode: CacheMode,
) -> list[FileEvidence]:
    paths = sorted(sessions_root.rglob("*.jsonl"))
    _initialize_cache_diagnostics(result, enabled=cache_mode != "disabled")
    if cache_mode == "disabled":
        return _collect_without_cache(paths, result)

    diagnostics_before = dict(result.diagnostics)
    warnings_before = dict(result.warnings)
    try:
        return _collect_with_cache(sessions_root, paths, result, mode=cache_mode)
    except (OSError, sqlite3.Error):
        result.diagnostics = diagnostics_before
        result.warnings = warnings_before
        result.diagnostics["scan_cache_enabled"] = 0
        result.bump_diagnostic("scan_cache_fallbacks")
        return _collect_without_cache(paths, result)


def scan_codex_usage(
    codex_home: Path,
    window: ScanWindow,
    *,
    now: datetime,
    cache_mode: CacheMode = "use",
) -> ScanResult:
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

    seen_fingerprints: set[str] = set()
    actual_threads: set[str] = set()
    imported_threads_seen: set[str] = set()
    continued_import_threads: set[str] = set()

    for evidence in _collect_file_evidence(
        codex_home,
        sessions_root,
        result,
        cache_mode=cache_mode,
    ):
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
            total_signature = event.total_signature
            input_tokens = event.usage_values[0]
            output_tokens = event.usage_values[3]

            timestamp = _parse_timestamp(event.timestamp)
            if is_imported and import_boundary is not None:
                if timestamp is None:
                    if input_tokens or output_tokens:
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

            if event.fingerprint in seen_fingerprints:
                result.bump_diagnostic("exact_duplicate_events_ignored")
                continue
            seen_fingerprints.add(event.fingerprint)

            if input_tokens == 0 and output_tokens == 0:
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

            usage = Usage(*event.usage_values)
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
