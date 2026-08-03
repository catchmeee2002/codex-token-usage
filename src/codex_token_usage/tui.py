from __future__ import annotations

import curses
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

from .cache import CacheMode
from .chart import (
    ChartBucket,
    build_daily_vertical_chart,
    build_hourly_vertical_chart,
    bucket_range_label,
    clip_display as _clip,
    compact_number as _compact_number,
    display_width as _display_width,
    hour_bucket_range_label,
    single_local_day,
)
from .model import ScanResult, ScanWindow, Usage
from .scanner import scan_codex_usage
from .timeparse import TimeParseError, build_window


SUPPORTED_LANGUAGES = ("zh", "en")
EFFORT_ORDER = {name: index for index, name in enumerate(("low", "medium", "high", "xhigh", "max", "ultra", "unknown"))}
EFFORT_COLUMN_COPY = {
    "zh": {
        "effort": "等级",
        "tokens": "用量",
        "share": "占比",
        "burn": "工作速率",
        "call": "调用中位",
        "turn": "回合中位",
        "reason": "推理占比",
        "cache": "缓存率",
        "samples": "样本",
    },
    "en": {
        "effort": "Effort",
        "tokens": "Tokens",
        "share": "Share",
        "burn": "Worker rate",
        "call": "Call p50",
        "turn": "Turn p50",
        "reason": "Reasoning",
        "cache": "Cache",
        "samples": "Turns",
    },
}


@dataclass(frozen=True)
class RangeChoice:
    key: str
    since: str | None = None
    all_time: bool = False
    custom: bool = False


RANGE_CHOICES = (
    RangeChoice("last_7d", since="7d"),
    RangeChoice("last_24h", since="24h"),
    RangeChoice("last_30d", since="30d"),
    RangeChoice("all_time", all_time=True),
    RangeChoice("custom", custom=True),
)


@dataclass
class ViewSnapshot:
    result: ScanResult
    chart_index: int
    chart_bucket_count: int
    selected_daily_bucket: ChartBucket | None
    view_kind: str
    status: str


CHOICE_COPY = {
    "zh": {
        "last_7d": ("最近 7 天", "默认滚动窗口"),
        "last_24h": ("滚动 24 小时", "跨自然日的连续 24 小时"),
        "last_30d": ("最近 30 天", "查看月度趋势"),
        "all_time": ("全部历史", "扫描本机全部记录"),
        "custom": ("自定义日期", "输入开始和结束日期"),
    },
    "en": {
        "last_7d": ("Last 7 days", "Default window"),
        "last_24h": ("Rolling 24 hours", "Continuous window across calendar days"),
        "last_30d": ("Last 30 days", "Monthly trend"),
        "all_time": ("All history", "All local records"),
        "custom": ("Custom dates", "Enter start/end"),
    },
}


TEXT = {
    "zh": {
        "ready": "准备扫描…",
        "need_custom": "请先输入自定义日期",
        "scanning": "正在扫描：{choice}…",
        "date_error": "日期输入错误：{error}",
        "scan_complete": "扫描完成：{count} 个文件（复用 {hits}，增量 {incremental}，完整 {full}）",
        "rebuild_complete": "强制重扫完成：{count} 个文件（完整 {full}）",
        "prompt_start": "开始日期 YYYY-MM-DD（留空取消）：",
        "prompt_end": "结束日期 YYYY-MM-DD（留空表示现在）：",
        "custom_canceled": "已取消自定义日期",
        "too_small": "终端窗口太小，请至少调整到 78×22。",
        "dashboard": "本机 Token 用量仪表盘",
        "effort_dashboard": "Effort 消耗分析",
        "range_menu": "统计范围",
        "footer_daily": "↑↓ 范围  ←→/[] 柱  Enter 下钻  Tab 页面  r 刷新  R 重扫  q 退出",
        "footer_zoom": "↑↓ 范围  ←→/[] 日期  Enter 下钻  Backspace 返回  r/R 刷新  q 退出",
        "footer_hourly": "↑↓ 范围  ←→ 小时  [] 日期  Backspace 返回  r/R 刷新  q 退出",
        "current": "当前：{scope}",
        "selected": "选中：{range}  {tokens} Token",
        "selected_day": "选中：{range}  {tokens} Token  · Enter 查看小时",
        "selected_range": "选中：{range}  {tokens} Token  · Enter 展开日期",
        "total": "总 Token",
        "approx": "约合",
        "input_output": "输入 / 输出",
        "cached_input": "缓存输入",
        "root_subagent": "主线程 / 子代理",
        "chart": "Token ↑  每日用量  日期 →",
        "hourly_chart": "Token ↑  每小时用量  小时 →",
        "partial": "  * 部分日",
        "day_in_progress": "  * 当日未结束",
        "bucket": "  {days}天/柱",
        "no_chart": "所选范围内没有可绘制的用量数据。",
        "warning": "警告：发现 {count} 个数据完整性问题",
        "effort_coverage": "Effort 归因：{coverage:.2f}%  模型：{models}",
        "effort_total": "已归因 Token：{tokens}",
        "effort_none": "所选范围内没有可归因的 Effort 数据。",
        "effort_explain_title": "指标说明",
        "effort_explain_1": "用量/占比：该等级总 Token / 占全部 Token 的比例",
        "effort_explain_2": "工作速率：总 Token ÷ Agent 工作小时（并行线程时间分别累计）",
        "effort_explain_3": "调用中位/回合中位：单次模型调用 / 单个 Turn 总 Token 的中位数",
        "effort_explain_4": "推理占比/缓存率/样本：推理输出÷输出 / 缓存输入÷输入 / Turn 数",
        "all_scope": "全部历史",
        "custom_scope": "自定义日期",
        "daily_detail_scope": "日期细分",
        "hourly_detail_scope": "{day} 小时详情",
        "today_limit": "已经是今天，不能继续进入未来日期",
        "no_records": "无记录",
        "all_range": "{first} 起，统计至 {end}",
        "language_changed": "界面语言已切换为中文",
        "tui_error": "codex-token-usage: 无法启动终端 UI：{error}",
    },
    "en": {
        "ready": "Ready to scan…",
        "need_custom": "Enter a custom date range first",
        "scanning": "Scanning: {choice}…",
        "date_error": "Invalid date input: {error}",
        "scan_complete": "Scan complete: {count} files ({hits} reused, {incremental} incremental, {full} full)",
        "rebuild_complete": "Forced rescan complete: {count} files ({full} full)",
        "prompt_start": "Start date YYYY-MM-DD (blank cancels): ",
        "prompt_end": "End date YYYY-MM-DD (blank means now): ",
        "custom_canceled": "Custom date range canceled",
        "too_small": "Terminal too small; resize it to at least 78x22.",
        "dashboard": "Local Token Usage Dashboard",
        "effort_dashboard": "Effort Usage Analysis",
        "range_menu": "Time range",
        "footer_daily": "↑↓ range  ←→/[] bar  Enter drill down  Tab page  r refresh  R rescan  q quit",
        "footer_zoom": "↑↓ range  ←→/[] date  Enter drill down  Backspace back  r/R refresh  q quit",
        "footer_hourly": "↑↓ range  ←→ hour  [] day  Backspace back  r/R refresh  q quit",
        "current": "Current: {scope}",
        "selected": "Selected: {range}  {tokens} tokens",
        "selected_day": "Selected: {range}  {tokens} tokens  · Enter for hours",
        "selected_range": "Selected: {range}  {tokens} tokens  · Enter to expand dates",
        "total": "Total tokens",
        "approx": "Compact",
        "input_output": "Input / output",
        "cached_input": "Cached input",
        "root_subagent": "Root / subagent",
        "chart": "Tokens ↑  Daily usage  Date →",
        "hourly_chart": "Tokens ↑  Hourly usage  Hour →",
        "partial": "  * partial",
        "day_in_progress": "  * day in progress",
        "bucket": "  {days}d/bar",
        "no_chart": "No usage data is available for this range.",
        "warning": "Warning: {count} data-integrity issues detected",
        "effort_coverage": "Effort coverage: {coverage:.2f}%  Models: {models}",
        "effort_total": "Attributed tokens: {tokens}",
        "effort_none": "No attributable effort data is available for this range.",
        "effort_explain_title": "Metric definitions",
        "effort_explain_1": "Tokens/share: level total / share of all tokens",
        "effort_explain_2": "Worker rate: tokens divided by summed agent worker-hours",
        "effort_explain_3": "Call/turn p50: median tokens per model call / turn",
        "effort_explain_4": "Reasoning/cache/turns: reasoning÷output / cached÷input / sample turns",
        "all_scope": "All history",
        "custom_scope": "Custom dates",
        "daily_detail_scope": "Daily detail",
        "hourly_detail_scope": "{day} hourly detail",
        "today_limit": "Already at today; future dates are unavailable",
        "no_records": "no records",
        "all_range": "From {first} through {end}",
        "language_changed": "Interface language switched to English",
        "tui_error": "codex-token-usage: unable to start terminal UI: {error}",
    },
}


def _language(value: str) -> str:
    return value if value in SUPPORTED_LANGUAGES else "zh"


def _choice_copy(choice: RangeChoice, language: str) -> tuple[str, str]:
    return CHOICE_COPY[_language(language)][choice.key]


def choice_labels(language: str) -> list[str]:
    return [_choice_copy(choice, language)[0] for choice in RANGE_CHOICES]


def _number(value: int) -> str:
    return f"{value:,}"


def _rate(value: float) -> str:
    if value <= 0:
        return "-"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M/h"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K/h"
    return f"{value:.0f}/h"


def effort_keys(result: ScanResult) -> list[str]:
    return sorted(
        (key for key, bucket in result.by_effort.items() if bucket.usage.total_tokens),
        key=lambda key: (EFFORT_ORDER.get(key, len(EFFORT_ORDER)), key),
    )


def effort_column_labels(language: str) -> list[str]:
    copy = EFFORT_COLUMN_COPY[_language(language)]
    return [
        copy[key]
        for key in ("effort", "tokens", "share", "burn", "call", "turn", "reason", "cache", "samples")
    ]


def _scope_name(window: ScanWindow, language: str, *, view_kind: str = "range") -> str:
    copy = TEXT[language]
    if view_kind == "hourly" and window.start is not None:
        day = window.start.astimezone(window.timezone).date().isoformat()
        return copy["hourly_detail_scope"].format(day=day)
    if view_kind == "zoom":
        return copy["daily_detail_scope"]
    if window.start is None:
        return copy["all_scope"]
    if window.label.startswith("rolling "):
        value = window.label.removeprefix("rolling ")
        if value == "24h":
            return "Rolling 24 hours" if language == "en" else "滚动 24 小时"
        if language == "en":
            units = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
            unit = units.get(value[-1:], "")
            return f"Last {value[:-1]} {unit}" if unit else window.label
        units = {"m": "分钟", "h": "小时", "d": "天", "w": "周"}
        unit = units.get(value[-1:], "")
        return f"最近 {value[:-1]} {unit}" if unit else window.label
    return copy["custom_scope"]


def _range_text(result: ScanResult, language: str) -> str:
    copy = TEXT[language]
    end = result.window.end.astimezone(result.window.timezone).strftime("%Y-%m-%d %H:%M")
    if result.window.start is None:
        first_day = min(result.daily, default=copy["no_records"])
        return copy["all_range"].format(first=first_day, end=end)
    start = result.window.start.astimezone(result.window.timezone).strftime("%Y-%m-%d %H:%M")
    return f"{start}  →  {end}"


class TokenUsageTui:
    def __init__(
        self,
        screen: curses.window,
        *,
        codex_home: Path,
        now: datetime,
        timezone_name: str | None,
        language: str,
        cache_mode: CacheMode = "use",
    ) -> None:
        self.screen = screen
        self.codex_home = codex_home
        self.now = now
        self.timezone_name = timezone_name
        self.language = _language(language)
        self.cursor = 0
        self.active_choice = 0
        self.chart_index = -1
        self.chart_bucket_count = 0
        self.page = "usage"
        self.result: ScanResult | None = None
        self.status = self._t("ready")
        self.custom_from: str | None = None
        self.custom_to: str | None = None
        self.view_kind = "range"
        self.view_stack: list[ViewSnapshot] = []
        self.selected_daily_bucket: ChartBucket | None = None
        self.cache_mode: CacheMode = "disabled" if cache_mode == "disabled" else "use"
        self.next_cache_mode: CacheMode | None = "rebuild" if cache_mode == "rebuild" else None
        self._init_screen()

    def _t(self, key: str, **values: object) -> str:
        return TEXT[self.language][key].format(**values)

    def _choice_text(self, choice: RangeChoice) -> tuple[str, str]:
        return _choice_copy(choice, self.language)

    def _init_screen(self) -> None:
        curses.curs_set(0)
        self.screen.keypad(True)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_GREEN, -1)

    def _write(self, y: int, x: int, text: str, *, width: int, attr: int = 0) -> None:
        height, screen_width = self.screen.getmaxyx()
        if y < 0 or y >= height or x < 0 or x >= screen_width or width <= 0:
            return
        clipped = _clip(text, min(width, screen_width - x - 1))
        try:
            self.screen.addstr(y, x, clipped, attr)
        except curses.error:
            pass

    def _window_for_choice(self, choice: RangeChoice) -> ScanWindow:
        return build_window(
            now=self.now,
            timezone_name=self.timezone_name,
            all_time=choice.all_time,
            since=choice.since,
            from_value=self.custom_from if choice.custom else None,
            to_value=self.custom_to if choice.custom else None,
        )

    def _window_for_dates(
        self,
        start: date,
        end: date,
        *,
        timezone_name: str,
        label: str,
    ) -> ScanWindow:
        window = build_window(
            now=self.now,
            timezone_name=timezone_name,
            all_time=False,
            since=None,
            from_value=start.isoformat(),
            to_value=end.isoformat(),
        )
        return ScanWindow(
            start=window.start,
            end=window.end,
            timezone=window.timezone,
            timezone_name=window.timezone_name,
            label=label,
        )

    def _scan_window(
        self,
        window: ScanWindow,
        *,
        cache_mode: CacheMode | None = None,
        reset_chart: bool,
        choice_label: str,
    ) -> None:
        if reset_chart:
            self.chart_index = -1
        self.chart_bucket_count = 0
        self.selected_daily_bucket = None
        self.status = self._t("scanning", choice=choice_label)
        self.result = None
        self._draw()
        selected_cache_mode = cache_mode or self.next_cache_mode or self.cache_mode
        self.next_cache_mode = None
        self.result = scan_codex_usage(
            self.codex_home,
            window,
            now=self.now,
            cache_mode=selected_cache_mode,
        )
        status_key = "rebuild_complete" if selected_cache_mode == "rebuild" else "scan_complete"
        self.status = self._t(
            status_key,
            count=self.result.diagnostics.get("session_files_scanned", 0),
            hits=self.result.diagnostics.get("session_files_cache_hits", 0),
            incremental=self.result.diagnostics.get("session_files_incrementally_parsed", 0),
            full=self.result.diagnostics.get("session_files_fully_parsed", 0),
        )

    def _load(
        self,
        index: int,
        *,
        prompt_custom: bool = True,
        cache_mode: CacheMode | None = None,
    ) -> None:
        choice = RANGE_CHOICES[index]
        if choice.custom:
            if prompt_custom and not self._prompt_custom_range():
                return
            if self.custom_from is None:
                self.status = self._t("need_custom")
                return
        self.now = datetime.now(timezone.utc)
        self.active_choice = index
        self.view_kind = "range"
        self.view_stack.clear()
        label, _ = self._choice_text(choice)
        try:
            window = self._window_for_choice(choice)
            self._scan_window(
                window,
                cache_mode=cache_mode,
                reset_chart=True,
                choice_label=label,
            )
        except TimeParseError as exc:
            self.status = self._t("date_error", error=exc)
            return

    def _prompt(self, prompt: str) -> str | None:
        height, width = self.screen.getmaxyx()
        self.screen.move(height - 2, 1)
        self.screen.clrtoeol()
        self._write(height - 2, 2, prompt, width=width - 4, attr=curses.A_BOLD)
        prompt_width = _display_width(prompt)
        curses.echo()
        curses.curs_set(1)
        try:
            raw = self.screen.getstr(height - 2, min(width - 2, 2 + prompt_width), 20)
        except curses.error:
            return None
        finally:
            curses.noecho()
            curses.curs_set(0)
        return raw.decode("utf-8", errors="replace").strip()

    def _prompt_custom_range(self) -> bool:
        start = self._prompt(self._t("prompt_start"))
        if not start:
            self.status = self._t("custom_canceled")
            return False
        end = self._prompt(self._t("prompt_end"))
        self.custom_from = start
        self.custom_to = end or None
        return True

    def _push_current_view(self) -> None:
        if self.result is None:
            return
        self.view_stack.append(
            ViewSnapshot(
                result=self.result,
                chart_index=self.chart_index,
                chart_bucket_count=self.chart_bucket_count,
                selected_daily_bucket=self.selected_daily_bucket,
                view_kind=self.view_kind,
                status=self.status,
            )
        )

    def _drill_down(self) -> None:
        if self.page != "usage" or self.result is None or self.selected_daily_bucket is None:
            return
        bucket = self.selected_daily_bucket
        self._push_current_view()
        self.now = datetime.now(timezone.utc)
        if bucket.start == bucket.end:
            self.view_kind = "hourly"
            label = self._t("hourly_detail_scope", day=bucket.start.isoformat())
            window = self._window_for_dates(
                bucket.start,
                bucket.end,
                timezone_name=self.result.window.timezone_name,
                label="single day",
            )
        else:
            self.view_kind = "zoom"
            label = self._t("daily_detail_scope")
            window = self._window_for_dates(
                bucket.start,
                bucket.end,
                timezone_name=self.result.window.timezone_name,
                label="drilldown range",
            )
        self._scan_window(window, reset_chart=True, choice_label=label)

    def _go_back(self) -> None:
        if not self.view_stack:
            return
        snapshot = self.view_stack.pop()
        self.result = snapshot.result
        self.chart_index = snapshot.chart_index
        self.chart_bucket_count = snapshot.chart_bucket_count
        self.selected_daily_bucket = snapshot.selected_daily_bucket
        self.view_kind = snapshot.view_kind
        self.status = snapshot.status

    def _refresh_current(self, *, cache_mode: CacheMode | None = None) -> None:
        if self.result is None:
            self._load(self.active_choice, prompt_custom=False, cache_mode=cache_mode)
            return
        self.now = datetime.now(timezone.utc)
        if self.view_kind == "range":
            window = self._window_for_choice(RANGE_CHOICES[self.active_choice])
        else:
            window = self.result.window
        label = _scope_name(window, self.language, view_kind=self.view_kind)
        self._scan_window(
            window,
            cache_mode=cache_mode,
            reset_chart=False,
            choice_label=label,
        )

    def _move_hourly_day(self, offset: int) -> None:
        if self.result is None or not self._is_hourly_view():
            return
        selected_day = single_local_day(self.result)
        if selected_day is None:
            return
        target = selected_day + timedelta(days=offset)
        today = self.result.generated_at.astimezone(self.result.window.timezone).date()
        if target > today:
            self.status = self._t("today_limit")
            return
        self.now = datetime.now(timezone.utc)
        self.view_kind = "hourly"
        window = self._window_for_dates(
            target,
            target,
            timezone_name=self.result.window.timezone_name,
            label="single day",
        )
        self._scan_window(
            window,
            reset_chart=True,
            choice_label=self._t("hourly_detail_scope", day=target.isoformat()),
        )

    def _footer_key(self) -> str:
        if self._is_hourly_view():
            return "footer_hourly"
        if self.view_kind == "zoom":
            return "footer_zoom"
        return "footer_daily"

    def _is_hourly_view(self) -> bool:
        return self.result is not None and single_local_day(self.result) is not None

    def _draw_frame(self, height: int, width: int, left_width: int) -> None:
        self.screen.border()
        for y in range(2, height - 2):
            try:
                self.screen.addch(y, left_width, curses.ACS_VLINE)
            except curses.error:
                pass
        try:
            self.screen.addch(2, 0, curses.ACS_LTEE)
            self.screen.addch(2, left_width, curses.ACS_PLUS)
            self.screen.addch(2, width - 1, curses.ACS_RTEE)
            self.screen.hline(2, 1, curses.ACS_HLINE, width - 2)
            self.screen.addch(height - 2, 0, curses.ACS_LTEE)
            self.screen.addch(height - 2, left_width, curses.ACS_PLUS)
            self.screen.addch(height - 2, width - 1, curses.ACS_RTEE)
            self.screen.hline(height - 2, 1, curses.ACS_HLINE, width - 2)
        except curses.error:
            pass

    def _draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 22 or width < 78:
            self._write(1, 2, self._t("too_small"), width=max(1, width - 4))
            self.screen.refresh()
            return

        left_width = 24
        self._draw_frame(height, width, left_width)
        title_attr = curses.A_BOLD | (curses.color_pair(1) if curses.has_colors() else 0)
        self._write(1, 2, "Codex Token Usage", width=left_width - 3, attr=title_attr)
        dashboard_key = "effort_dashboard" if self.page == "effort" else "dashboard"
        self._write(1, left_width + 2, self._t(dashboard_key), width=width - left_width - 4, attr=title_attr)
        self._write(3, 2, self._t("range_menu"), width=left_width - 4, attr=curses.A_BOLD)

        for index, choice in enumerate(RANGE_CHOICES):
            label, description = self._choice_text(choice)
            prefix = "●" if index == self.active_choice else " "
            text = f"{prefix} {label}"
            attr = curses.A_REVERSE | curses.A_BOLD if index == self.cursor else curses.A_NORMAL
            self._write(5 + index * 2, 2, text, width=left_width - 4, attr=attr)
            if index == self.cursor:
                self._write(
                    6 + index * 2,
                    4,
                    description,
                    width=left_width - 6,
                    attr=curses.A_DIM,
                )

        x = left_width + 2
        content_width = width - x - 2
        if self.result is None:
            loading_attr = curses.A_BOLD | (curses.color_pair(2) if curses.has_colors() else 0)
            self._write(5, x, self.status, width=content_width, attr=loading_attr)
        else:
            if self.page == "effort":
                self._draw_effort_result(x=x, width=content_width, height=height)
            else:
                self._draw_result(x=x, width=content_width, height=height)

        self._write(
            height - 1,
            2,
            self._t(self._footer_key()),
            width=width - 4,
            attr=curses.A_DIM,
        )
        self.screen.refresh()

    def _draw_result(self, *, x: int, width: int, height: int) -> None:
        assert self.result is not None
        result = self.result
        green = curses.color_pair(3) if curses.has_colors() else 0
        self._write(
            3,
            x,
            self._t(
                "current",
                scope=_scope_name(
                    result.window,
                    self.language,
                    view_kind="hourly" if self._is_hourly_view() else self.view_kind,
                ),
            ),
            width=width,
            attr=curses.A_BOLD | green,
        )
        self._write(4, x, _range_text(result, self.language), width=width, attr=curses.A_DIM)
        available_rows = max(0, height - (16 if result.warnings else 14))
        hourly = single_local_day(result) is not None
        self.selected_daily_bucket = None
        chart = (
            build_hourly_vertical_chart(
                result,
                width=width,
                height=max(3, available_rows - 2),
                language=self.language,
                selected_index=self.chart_index,
            )
            if hourly
            else build_daily_vertical_chart(
                result,
                width=width,
                height=max(3, available_rows - 2),
                language=self.language,
                selected_index=self.chart_index,
            )
        )
        if chart is None or chart.selected_index is None:
            self.chart_bucket_count = 0
        else:
            self.chart_index = chart.selected_index
            self.chart_bucket_count = len(chart.buckets)
            bucket = chart.buckets[chart.selected_index]
            selected_range = (
                hour_bucket_range_label(bucket)
                if hourly
                else bucket_range_label(bucket) + ("*" if bucket.partial else "")
            )
            if not hourly:
                self.selected_daily_bucket = bucket
                selected_key = "selected_day" if bucket.start == bucket.end else "selected_range"
            else:
                selected_key = "selected"
            self._write(
                5,
                x,
                self._t(
                    selected_key,
                    range=selected_range,
                    tokens=_number(bucket.total_tokens),
                ),
                width=width,
                attr=curses.A_BOLD,
            )

        label_width = 18
        self._write(6, x, self._t("total"), width=label_width, attr=curses.A_BOLD)
        self._write(6, x + label_width, _number(result.usage.total_tokens), width=width - label_width, attr=curses.A_BOLD)
        self._write(7, x, self._t("approx"), width=label_width)
        self._write(7, x + label_width, _compact_number(result.usage.total_tokens, self.language), width=width - label_width)
        self._write(8, x, self._t("input_output"), width=label_width)
        self._write(
            8,
            x + label_width,
            f"{_number(result.usage.input_tokens)} / {_number(result.usage.output_tokens)}",
            width=width - label_width,
        )
        cached_ratio = (
            result.usage.cached_input_tokens / result.usage.input_tokens * 100
            if result.usage.input_tokens
            else 0.0
        )
        self._write(9, x, self._t("cached_input"), width=label_width)
        ratio = f" ({cached_ratio:.1f}%)" if self.language == "en" else f"（{cached_ratio:.1f}%）"
        self._write(
            9,
            x + label_width,
            f"{_number(result.usage.cached_input_tokens)}{ratio}",
            width=width - label_width,
        )
        root = result.by_thread_type.get("root", Usage()).total_tokens
        subagent = result.by_thread_type.get("subagent", Usage()).total_tokens
        self._write(10, x, self._t("root_subagent"), width=label_width)
        self._write(
            10,
            x + label_width,
            f"{_compact_number(root, self.language)} / {_compact_number(subagent, self.language)}",
            width=width - label_width,
        )

        chart_title = self._t("hourly_chart" if hourly else "chart")
        if chart is not None and not hourly and chart.bucket_days > 1:
            chart_title += self._t("bucket", days=chart.bucket_days)
        if chart is not None and chart.partial:
            chart_title += self._t("day_in_progress" if hourly else "partial")
        self._write(11, x, chart_title, width=width, attr=curses.A_BOLD)
        if chart is None:
            self._write(12, x, self._t("no_chart"), width=width, attr=curses.A_DIM)
        else:
            for offset, row in enumerate(chart.lines):
                self._write(12 + offset, x, row, width=width)

        if result.warnings:
            warning_attr = curses.A_BOLD | (curses.color_pair(2) if curses.has_colors() else 0)
            self._write(
                height - 4,
                x,
                self._t("warning", count=sum(result.warnings.values())),
                width=width,
                attr=warning_attr,
            )

    def _draw_effort_result(self, *, x: int, width: int, height: int) -> None:
        assert self.result is not None
        result = self.result
        green = curses.color_pair(3) if curses.has_colors() else 0
        self._write(
            3,
            x,
            self._t("current", scope=_scope_name(result.window, self.language)),
            width=width,
            attr=curses.A_BOLD | green,
        )
        self._write(4, x, _range_text(result, self.language), width=width, attr=curses.A_DIM)

        keys = effort_keys(result)
        attributed = sum(result.by_effort[key].usage.total_tokens for key in keys if key != "unknown")
        coverage = attributed / result.usage.total_tokens * 100 if result.usage.total_tokens else 0.0
        models = sorted(
            model
            for key in keys
            if key != "unknown"
            for model in result.by_effort[key].models
        )
        model_text = ", ".join(dict.fromkeys(models)) if models else "unknown"
        self._write(5, x, self._t("effort_coverage", coverage=coverage, models=model_text), width=width)
        self._write(6, x, self._t("effort_total", tokens=_number(attributed)), width=width, attr=curses.A_BOLD)
        if not keys:
            self._write(8, x, self._t("effort_none"), width=width, attr=curses.A_DIM)
            return

        if width >= 92:
            columns = (
                (0, 8, "effort"), (9, 12, "tokens"), (22, 8, "share"),
                (31, 10, "burn"), (42, 11, "call"), (54, 12, "turn"),
                (67, 9, "reason"), (77, 9, "cache"), (87, 5, "samples"),
            )
        elif width >= 66:
            columns = (
                (0, 9, "effort"), (10, 13, "tokens"), (24, 8, "share"),
                (33, 13, "call"), (47, 12, "reason"), (60, 6, "samples"),
            )
        else:
            columns = (
                (0, 8, "effort"), (9, 12, "tokens"), (22, 8, "share"),
                (31, 11, "reason"), (43, 6, "samples"),
            )
        column_copy = EFFORT_COLUMN_COPY[self.language]
        for offset, column_width, column_key in columns:
            self._write(
                8,
                x + offset,
                column_copy[column_key],
                width=column_width,
                attr=curses.A_BOLD | curses.A_DIM,
            )

        total = result.usage.total_tokens
        max_rows = 5 if height < 26 else 7
        for index, key in enumerate(keys[:max_rows]):
            bucket = result.by_effort[key]
            share = bucket.usage.total_tokens / total * 100 if total else 0.0
            values = {
                "effort": key,
                "tokens": _compact_number(bucket.usage.total_tokens, self.language),
                "share": f"{share:.1f}%",
                "burn": _rate(bucket.tokens_per_worker_hour),
                "call": _compact_number(bucket.median_event_tokens, self.language),
                "turn": _compact_number(bucket.median_turn_tokens, self.language),
                "reason": f"{bucket.reasoning_ratio * 100:.1f}%",
                "cache": f"{bucket.cache_ratio * 100:.1f}%",
                "samples": str(bucket.turns),
            }
            if key in ("max", "ultra"):
                attr = curses.color_pair(2) if curses.has_colors() else curses.A_BOLD
            elif key in ("high", "xhigh"):
                attr = curses.color_pair(1) if curses.has_colors() else curses.A_BOLD
            else:
                attr = curses.color_pair(3) if curses.has_colors() else 0
            for offset, column_width, column_key in columns:
                self._write(10 + index, x + offset, values[column_key], width=column_width, attr=attr)

        explanation_keys = (
            "effort_explain_title",
            "effort_explain_1",
            "effort_explain_2",
            "effort_explain_3",
            "effort_explain_4",
        )
        explanation_start = height - 9 if height >= 28 else height - 6
        if height < 28:
            explanation_keys = explanation_keys[1:]
        for offset, text_key in enumerate(explanation_keys):
            attr = curses.A_BOLD if text_key == "effort_explain_title" else curses.A_DIM
            self._write(explanation_start + offset, x, self._t(text_key), width=width, attr=attr)
        if result.warnings:
            warning_attr = curses.A_BOLD | (curses.color_pair(2) if curses.has_colors() else 0)
            self._write(
                height - 3,
                x,
                self._t("warning", count=sum(result.warnings.values())),
                width=width,
                attr=warning_attr,
            )

    def _toggle_language(self) -> None:
        self.language = "en" if self.language == "zh" else "zh"
        self.status = self._t("language_changed")

    def _toggle_page(self) -> None:
        self.page = "effort" if self.page == "usage" else "usage"

    def _move_chart_selection(self, offset: int) -> None:
        if self.chart_bucket_count <= 0:
            return
        self.chart_index = max(
            0,
            min(self.chart_bucket_count - 1, self.chart_index + offset),
        )

    def run(self) -> int:
        self._load(0)
        while True:
            self._draw()
            key = self.screen.getch()
            if key in (ord("q"), ord("Q"), 27):
                return 0
            if key in (curses.KEY_UP, ord("k"), ord("K")):
                self.cursor = (self.cursor - 1) % len(RANGE_CHOICES)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                self.cursor = (self.cursor + 1) % len(RANGE_CHOICES)
            elif key in (curses.KEY_ENTER, 10, 13):
                if self.cursor != self.active_choice:
                    self._load(self.cursor)
                else:
                    self._drill_down()
            elif key == ord("r"):
                self._refresh_current()
            elif key == ord("R"):
                self._refresh_current(
                    cache_mode="disabled" if self.cache_mode == "disabled" else "rebuild",
                )
            elif key == curses.KEY_LEFT:
                self._move_chart_selection(-1)
            elif key == curses.KEY_RIGHT:
                self._move_chart_selection(1)
            elif key == ord("["):
                if self._is_hourly_view():
                    self._move_hourly_day(-1)
                else:
                    self._move_chart_selection(-1)
            elif key == ord("]"):
                if self._is_hourly_view():
                    self._move_hourly_day(1)
                else:
                    self._move_chart_selection(1)
            elif key in (curses.KEY_BACKSPACE, 8, 127):
                self._go_back()
            elif key in (ord("l"), ord("L")):
                self._toggle_language()
            elif key in (9, ord("e"), ord("E")):
                self._toggle_page()
            elif key == curses.KEY_RESIZE:
                continue


def run_tui(
    codex_home: Path,
    *,
    now: datetime | None = None,
    timezone_name: str | None = None,
    language: str = "zh",
    cache_mode: CacheMode = "use",
    stderr: TextIO,
) -> int:
    language = _language(language)
    fixed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        return curses.wrapper(
            lambda screen: TokenUsageTui(
                screen,
                codex_home=codex_home,
                now=fixed_now,
                timezone_name=timezone_name,
                language=language,
                cache_mode=cache_mode,
            ).run()
        )
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        print(TEXT[language]["tui_error"].format(error=exc), file=stderr)
        return 1
