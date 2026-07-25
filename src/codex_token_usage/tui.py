from __future__ import annotations

import curses
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from .chart import (
    build_daily_vertical_chart,
    clip_display as _clip,
    compact_number as _compact_number,
    display_width as _display_width,
)
from .model import ScanResult, ScanWindow, Usage
from .scanner import scan_codex_usage
from .timeparse import TimeParseError, build_window


SUPPORTED_LANGUAGES = ("zh", "en")


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


CHOICE_COPY = {
    "zh": {
        "last_7d": ("最近 7 天", "默认滚动窗口"),
        "last_24h": ("最近 24 小时", "查看一天内的用量"),
        "last_30d": ("最近 30 天", "查看月度趋势"),
        "all_time": ("全部历史", "扫描本机全部记录"),
        "custom": ("自定义日期", "输入开始和结束日期"),
    },
    "en": {
        "last_7d": ("Last 7 days", "Default window"),
        "last_24h": ("Last 24 hours", "One-day usage"),
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
        "scan_complete": "扫描完成：{count} 个会话文件",
        "prompt_start": "开始日期 YYYY-MM-DD（留空取消）：",
        "prompt_end": "结束日期 YYYY-MM-DD（留空表示现在）：",
        "custom_canceled": "已取消自定义日期",
        "too_small": "终端窗口太小，请至少调整到 78×22。",
        "dashboard": "本机 Token 用量仪表盘",
        "range_menu": "统计范围",
        "footer": "↑↓/jk 选择  Enter 应用  r 刷新  l English  q/Esc 退出",
        "current": "当前：{scope}",
        "total": "总 Token",
        "approx": "约合",
        "input_output": "输入 / 输出",
        "cached_input": "缓存输入",
        "root_subagent": "主线程 / 子代理",
        "chart": "Token ↑  每日用量  日期 →",
        "partial": "  * 部分日",
        "bucket": "  {days}天/柱",
        "no_chart": "所选范围内没有可绘制的每日数据。",
        "warning": "警告：发现 {count} 个数据完整性问题",
        "all_scope": "全部历史",
        "custom_scope": "自定义日期",
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
        "scan_complete": "Scan complete: {count} session files",
        "prompt_start": "Start date YYYY-MM-DD (blank cancels): ",
        "prompt_end": "End date YYYY-MM-DD (blank means now): ",
        "custom_canceled": "Custom date range canceled",
        "too_small": "Terminal too small; resize it to at least 78x22.",
        "dashboard": "Local Token Usage Dashboard",
        "range_menu": "Time range",
        "footer": "↑↓/jk select  Enter apply  r refresh  l 中文  q/Esc quit",
        "current": "Current: {scope}",
        "total": "Total tokens",
        "approx": "Compact",
        "input_output": "Input / output",
        "cached_input": "Cached input",
        "root_subagent": "Root / subagent",
        "chart": "Tokens ↑  Daily usage  Date →",
        "partial": "  * partial",
        "bucket": "  {days}d/bar",
        "no_chart": "No daily data is available for this range.",
        "warning": "Warning: {count} data-integrity issues detected",
        "all_scope": "All history",
        "custom_scope": "Custom dates",
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


def _scope_name(window: ScanWindow, language: str) -> str:
    copy = TEXT[language]
    if window.start is None:
        return copy["all_scope"]
    if window.label.startswith("rolling "):
        value = window.label.removeprefix("rolling ")
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
    ) -> None:
        self.screen = screen
        self.codex_home = codex_home
        self.now = now
        self.timezone_name = timezone_name
        self.language = _language(language)
        self.cursor = 0
        self.active_choice = 0
        self.result: ScanResult | None = None
        self.status = self._t("ready")
        self.custom_from: str | None = None
        self.custom_to: str | None = None
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

    def _load(self, index: int, *, prompt_custom: bool = True) -> None:
        choice = RANGE_CHOICES[index]
        if choice.custom:
            if prompt_custom and not self._prompt_custom_range():
                return
            if self.custom_from is None:
                self.status = self._t("need_custom")
                return
        self.now = datetime.now(timezone.utc)
        self.active_choice = index
        label, _ = self._choice_text(choice)
        self.status = self._t("scanning", choice=label)
        self.result = None
        self._draw()
        try:
            window = self._window_for_choice(choice)
            self.result = scan_codex_usage(self.codex_home, window, now=self.now)
        except TimeParseError as exc:
            self.status = self._t("date_error", error=exc)
            return
        self.status = self._t(
            "scan_complete",
            count=self.result.diagnostics.get("session_files_scanned", 0),
        )

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
        self._write(1, left_width + 2, self._t("dashboard"), width=width - left_width - 4, attr=title_attr)
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
            self._draw_result(x=x, width=content_width, height=height)

        self._write(height - 1, 2, self._t("footer"), width=width - 4, attr=curses.A_DIM)
        self.screen.refresh()

    def _draw_result(self, *, x: int, width: int, height: int) -> None:
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
        label_width = 18
        self._write(6, x, self._t("total"), width=label_width, attr=curses.A_BOLD)
        self._write(
            6,
            x + label_width,
            _number(result.usage.total_tokens),
            width=width - label_width,
            attr=curses.A_BOLD,
        )
        self._write(7, x, self._t("approx"), width=label_width)
        self._write(
            7,
            x + label_width,
            _compact_number(result.usage.total_tokens, self.language),
            width=width - label_width,
        )
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

        available_rows = max(0, height - (16 if result.warnings else 14))
        chart = build_daily_vertical_chart(
            result,
            width=width,
            height=max(3, available_rows - 2),
            language=self.language,
        )
        chart_title = self._t("chart")
        if chart is not None and chart.bucket_days > 1:
            chart_title += self._t("bucket", days=chart.bucket_days)
        if chart is not None and chart.partial:
            chart_title += self._t("partial")
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

    def _toggle_language(self) -> None:
        self.language = "en" if self.language == "zh" else "zh"
        self.status = self._t("language_changed")

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
                self._load(self.cursor)
            elif key in (ord("r"), ord("R")):
                self._load(self.active_choice, prompt_custom=False)
            elif key in (ord("l"), ord("L")):
                self._toggle_language()
            elif key == curses.KEY_RESIZE:
                continue


def run_tui(
    codex_home: Path,
    *,
    now: datetime | None = None,
    timezone_name: str | None = None,
    language: str = "zh",
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
            ).run()
        )
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        print(TEXT[language]["tui_error"].format(error=exc), file=stderr)
        return 1
