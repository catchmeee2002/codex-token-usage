from __future__ import annotations

from datetime import datetime

from .chart import build_daily_vertical_chart, bucket_range_label
from .model import ScanResult, Usage


WARNING_TEXT_EN = {
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
    "subagent_history_boundary_missing": (
        "a subagent file had token events but no structured task-trigger boundary; "
        "its events were retained"
    ),
    "token_counter_resets": "cumulative token counters decreased; a new segment was counted",
    "truncated_tail_lines": "unfinished final JSONL records were ignored",
    "unreadable_session_files": "session files could not be read",
}

WARNING_TEXT_ZH = {
    "ambiguous_import_events": "导入事件缺少可用时间戳，已排除",
    "auth_status_unknown": "无法确定当前 Codex 认证方式",
    "current_auth_is_not_api_key": "当前 Codex 认证方式不是 API Key",
    "files_changed_during_scan": "扫描期间会话文件发生变化，本次只读取稳定前缀",
    "import_evidence_mismatches": "导入账本与会话导入标记不一致",
    "invalid_import_ledger": "无法解析导入会话账本",
    "invalid_import_ledger_records": "导入会话账本中的无效记录已跳过",
    "invalid_session_start_timestamps": "部分会话开始时间无法解析",
    "invalid_token_event_timestamps": "部分 Token 事件时间戳无效",
    "invalid_token_usage_events": "部分 Token 计数无效，已跳过",
    "malformed_json_lines": "格式错误的非末尾 JSONL 记录已跳过",
    "session_files_without_metadata": "缺少会话元数据的文件已跳过",
    "session_files_without_thread_id": "缺少线程 ID 的会话文件已跳过",
    "sessions_directory_missing": "Codex 会话目录不存在",
    "subagent_history_boundary_missing": "子代理文件缺少结构化任务触发边界，已保留其中的 Token 事件",
    "token_counter_resets": "累计 Token 计数发生回退，已按新分段统计",
    "truncated_tail_lines": "未写完的末尾 JSONL 记录已忽略",
    "unreadable_session_files": "部分会话文件无法读取",
}

def _number(value: int) -> str:
    return f"{value:,}"


def _local_time(value: datetime, result: ScanResult) -> str:
    return value.astimezone(result.window.timezone).isoformat(timespec="seconds")


def _chart_section(result: ScanResult, *, language: str) -> list[str]:
    chart = build_daily_vertical_chart(result, width=78, height=8, language=language)
    if chart is None:
        return [
            "所选范围内没有带时间戳的 Token 事件。"
            if language == "zh"
            else "No timed token events matched the selected window."
        ]
    if language == "zh":
        title = "Token ↑  每日用量  日期 →"
        if chart.bucket_days > 1:
            title += f"  {chart.bucket_days}天/柱"
        if chart.partial:
            title += "  * 部分日"
    else:
        title = "Tokens ↑  Daily usage  Date →"
        if chart.bucket_days > 1:
            title += f"  {chart.bucket_days}d/bar"
        if chart.partial:
            title += "  * partial"
    labels = [
        bucket_range_label(bucket) + ("*" if bucket.partial else "")
        for bucket in chart.buckets
    ]
    label_width = max(len(label) for label in labels)
    token_width = max(len(_number(bucket.total_tokens)) for bucket in chart.buckets)
    detail_title = "精确值" if language == "zh" else "Exact values"
    details = [
        f"{label.ljust(label_width)}  {_number(bucket.total_tokens).rjust(token_width)}"
        for label, bucket in zip(labels, chart.buckets)
    ]
    return [title, *chart.lines, "", detail_title, *details]


def _duration_zh(label: str) -> str:
    value = label.removeprefix("rolling ")
    units = {"m": "分钟", "h": "小时", "d": "天", "w": "周"}
    if len(value) > 1 and value[-1] in units:
        return f"{value[:-1]} {units[value[-1]]}"
    return value


def _usage_lines_zh(usage: Usage) -> list[str]:
    lines = [
        f"总 Token：       {_number(usage.total_tokens)}",
        f"输入 Token：     {_number(usage.input_tokens)}",
        f"  缓存输入：     {_number(usage.cached_input_tokens)}",
        f"  非缓存输入：   {_number(usage.uncached_input_tokens)}",
    ]
    if usage.cache_write_input_tokens:
        lines.append(f"  缓存写入输入： {_number(usage.cache_write_input_tokens)}")
    lines.extend(
        [
            f"输出 Token：     {_number(usage.output_tokens)}",
            f"  推理输出：     {_number(usage.reasoning_output_tokens)}",
        ]
    )
    return lines


def _usage_lines_en(usage: Usage) -> list[str]:
    lines = [
        f"Total tokens:           {_number(usage.total_tokens)}",
        f"Input tokens:           {_number(usage.input_tokens)}",
        f"  Cached input:         {_number(usage.cached_input_tokens)}",
        f"  Uncached input:       {_number(usage.uncached_input_tokens)}",
    ]
    if usage.cache_write_input_tokens:
        lines.append(f"  Cache-write input:    {_number(usage.cache_write_input_tokens)}")
    lines.extend(
        [
            f"Output tokens:          {_number(usage.output_tokens)}",
            f"  Reasoning output:     {_number(usage.reasoning_output_tokens)}",
        ]
    )
    return lines


def _render_zh(result: ScanResult, *, include_daily: bool) -> str:
    if result.window.start is None:
        window_lines = [
            "统计范围：全部历史",
            f"统计截止：{_local_time(result.window.end, result)}",
        ]
    elif result.window.label.startswith("rolling "):
        default_text = "默认" if result.window.label == "rolling 7d" else ""
        window_lines = [
            f"统计范围：⚠ 最近 {_duration_zh(result.window.label)}（{default_text}滚动窗口，不是全部历史）",
            (
                f"时间区间：{_local_time(result.window.start, result)} 至 "
                f"{_local_time(result.window.end, result)}（结束时间不含）"
            ),
            "查看全部历史：codex-token-usage --all",
        ]
    else:
        window_lines = [
            "统计范围：自定义区间",
            (
                f"时间区间：{_local_time(result.window.start, result)} 至 "
                f"{_local_time(result.window.end, result)}（结束时间不含）"
            ),
        ]

    auth_mode = result.auth_mode or "未知"
    lines = [
        "Codex Token 使用统计",
        *window_lines,
        f"当前认证方式：{auth_mode}",
        "历史会话日志无法识别每次调用所使用的 API Key。",
        "",
        *_usage_lines_zh(result.usage),
    ]

    if include_daily:
        lines.extend(["", *_chart_section(result, language="zh")])

    lines.extend(["", "按线程类型"])
    thread_labels = {"root": "主线程", "subagent": "子代理", "unknown": "未知"}
    for key in ("root", "subagent", "unknown"):
        usage = result.by_thread_type.get(key, Usage())
        if usage.total_tokens or key != "unknown":
            lines.append(f"  {thread_labels[key]}：{_number(usage.total_tokens)} Token")

    diagnostics = result.diagnostics
    lines.extend(
        [
            "",
            "导入历史处理",
            f"  导入账本记录：       {_number(diagnostics.get('import_ledger_records', 0))}",
            f"  发现的导入线程：     {_number(diagnostics.get('imported_threads_seen', 0))}",
            f"  排除的导入历史事件： {_number(diagnostics.get('import_history_events_excluded', 0))}",
            f"  排除的合成导入事件： {_number(diagnostics.get('import_synthetic_events_excluded', 0))}",
            f"  后续继续使用的线程： {_number(diagnostics.get('continued_import_threads', 0))}",
            "",
            "数据完整性",
            f"  扫描会话文件：       {_number(diagnostics.get('session_files_scanned', 0))}",
            f"  计入 Token 事件：    {_number(diagnostics.get('token_events_counted', 0))}",
            f"  排除子代理继承历史： {_number(diagnostics.get('subagent_history_events_excluded', 0))}",
            f"  忽略重复快照：       {_number(diagnostics.get('duplicate_token_snapshots_ignored', 0))}",
            f"  忽略完全重复事件：   {_number(diagnostics.get('exact_duplicate_events_ignored', 0))}",
        ]
    )

    if result.warnings:
        lines.extend(["", "警告"])
        for code, count in sorted(result.warnings.items()):
            message = WARNING_TEXT_ZH.get(code, code.replace("_", " "))
            lines.append(f"  {code}（{count}）：{message}")
    return "\n".join(lines) + "\n"


def _render_en(result: ScanResult, *, include_daily: bool) -> str:
    if result.window.start is None:
        window_lines = [
            "Scope: all history",
            f"Through: {_local_time(result.window.end, result)}",
        ]
    elif result.window.label.startswith("rolling "):
        default_text = "default " if result.window.label == "rolling 7d" else ""
        window_lines = [
            f"Scope: WARNING: {result.window.label} ({default_text}rolling window, not all history)",
            (
                f"Range: {_local_time(result.window.start, result)} through "
                f"{_local_time(result.window.end, result)} (end exclusive)"
            ),
            "View all history: codex-token-usage --all",
        ]
    else:
        window_lines = [
            "Scope: custom range",
            (
                f"Range: {_local_time(result.window.start, result)} through "
                f"{_local_time(result.window.end, result)} (end exclusive)"
            ),
        ]

    auth_mode = result.auth_mode or "unknown"
    lines = [
        "Codex token usage",
        *window_lines,
        f"Current auth mode: {auth_mode}",
        "Historical session logs do not identify the API key that was used.",
        "",
        *_usage_lines_en(result.usage),
    ]

    if include_daily:
        lines.extend(["", *_chart_section(result, language="en")])

    lines.extend(["", "By thread type"])
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
            f"  Subagent history excluded:   {_number(diagnostics.get('subagent_history_events_excluded', 0))}",
            f"  Duplicate snapshots ignored: {_number(diagnostics.get('duplicate_token_snapshots_ignored', 0))}",
            f"  Exact duplicates ignored:    {_number(diagnostics.get('exact_duplicate_events_ignored', 0))}",
        ]
    )

    if result.warnings:
        lines.extend(["", "Warnings"])
        for code, count in sorted(result.warnings.items()):
            message = WARNING_TEXT_EN.get(code, code.replace("_", " "))
            lines.append(f"  {code} ({count}): {message}")
    return "\n".join(lines) + "\n"


def render_human(result: ScanResult, *, include_daily: bool, language: str = "zh") -> str:
    if language == "en":
        return _render_en(result, include_daily=include_daily)
    return _render_zh(result, include_daily=include_daily)
