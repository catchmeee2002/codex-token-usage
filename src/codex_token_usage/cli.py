from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, TextIO

from . import __version__
from .render import render_human
from .scanner import scan_codex_usage
from .timeparse import TimeParseError, build_window


CLI_COPY = {
    "zh": {
        "description": "审计本机 Codex Token 用量，并排除导入的 Claude Code 历史。不指定时间参数时仅统计最近 7 天。",
        "epilog": "查看全部历史：codex-token-usage --all",
        "since": "滚动时间窗口，例如 24h、7d 或 2w",
        "from": "包含该时间的 ISO 起点",
        "to": "不包含该 ISO 日期时间；仅传日期时包含整天",
        "all": "统计全部历史",
        "timezone": "用于日期解析和每日统计的 IANA 时区",
        "codex_home": "覆盖 CODEX_HOME 路径",
        "json": "输出带稳定 schema 版本的 JSON",
        "no_daily": "隐藏每日趋势图",
        "ui": "进入全屏交互式终端 UI",
        "text": "强制使用非交互文本输出",
        "lang": "人类可读输出和 UI 语言，默认 zh",
        "strict": "出现完整性或认证警告时返回非零状态",
        "ui_text_conflict": "codex-token-usage: error: --ui 与 --text 不能同时使用",
        "ui_filter_conflict": "codex-token-usage: error: --ui 只能与 --lang、--timezone 或 --codex-home 搭配使用",
        "tty_required": "codex-token-usage: error: 终端 UI 需要交互式 TTY",
    },
    "en": {
        "description": "Audit local Codex token usage while excluding imported Claude Code history. Without a time option, text mode covers only the rolling last seven days.",
        "epilog": "View all history: codex-token-usage --all",
        "since": "rolling window such as 24h, 7d, or 2w",
        "from": "inclusive ISO start",
        "to": "exclusive ISO datetime, or an inclusive ISO date",
        "all": "scan all history",
        "timezone": "IANA timezone for naive dates and daily buckets",
        "codex_home": "override the CODEX_HOME path",
        "json": "emit stable schema-versioned JSON",
        "no_daily": "hide the daily chart",
        "ui": "open the full-screen interactive terminal UI",
        "text": "force non-interactive text output",
        "lang": "human-readable output and UI language; default: zh",
        "strict": "return non-zero on integrity or authentication warnings",
        "ui_text_conflict": "codex-token-usage: error: --ui and --text cannot be combined",
        "ui_filter_conflict": "codex-token-usage: error: --ui can only be combined with --lang, --timezone, or --codex-home",
        "tty_required": "codex-token-usage: error: the terminal UI requires an interactive TTY",
    },
}


def _requested_language(argv: Sequence[str]) -> str:
    for index, value in enumerate(argv):
        if value == "--lang" and index + 1 < len(argv):
            return "en" if argv[index + 1] == "en" else "zh"
        if value.startswith("--lang="):
            return "en" if value.partition("=")[2] == "en" else "zh"
    return "zh"


def build_parser(language: str = "zh") -> argparse.ArgumentParser:
    language = "en" if language == "en" else "zh"
    copy = CLI_COPY[language]
    parser = argparse.ArgumentParser(
        prog="codex-token-usage",
        description=copy["description"],
        epilog=copy["epilog"],
    )
    parser.add_argument("--since", metavar="DURATION", help=copy["since"])
    parser.add_argument("--from", dest="from_value", metavar="ISO", help=copy["from"])
    parser.add_argument(
        "--to",
        dest="to_value",
        metavar="ISO",
        help=copy["to"],
    )
    parser.add_argument("--all", dest="all_time", action="store_true", help=copy["all"])
    parser.add_argument("--timezone", help=copy["timezone"])
    parser.add_argument("--codex-home", type=Path, help=copy["codex_home"])
    parser.add_argument("--json", action="store_true", help=copy["json"])
    parser.add_argument("--no-daily", action="store_true", help=copy["no_daily"])
    parser.add_argument("--ui", action="store_true", help=copy["ui"])
    parser.add_argument("--text", action="store_true", help=copy["text"])
    parser.add_argument(
        "--lang",
        choices=("zh", "en"),
        default="zh",
        help=copy["lang"],
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=copy["strict"],
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _codex_home(argument: Path | None) -> Path:
    if argument is not None:
        return argument.expanduser()
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def main(
    argv: Sequence[str] | None = None,
    *,
    now: datetime | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    requested_language = _requested_language(raw_argv)
    parser = build_parser(requested_language)
    args = parser.parse_args(raw_argv)
    copy = CLI_COPY[args.lang]
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if args.ui and args.text:
        print(copy["ui_text_conflict"], file=stderr)
        return 2
    ui_conflicts = any(
        (
            args.all_time,
            args.since,
            args.from_value,
            args.to_value,
            args.json,
            args.no_daily,
            args.strict,
        )
    )
    if args.ui and ui_conflicts:
        print(copy["ui_filter_conflict"], file=stderr)
        return 2

    implicit_ui = (
        not raw_argv
        and stdout is sys.stdout
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )
    if args.ui or implicit_ui:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print(copy["tty_required"], file=stderr)
            return 2
        from .tui import run_tui

        return run_tui(
            _codex_home(args.codex_home),
            now=now,
            timezone_name=args.timezone,
            language=args.lang,
            stderr=stderr,
        )

    try:
        window = build_window(
            now=now,
            timezone_name=args.timezone,
            all_time=args.all_time,
            since=args.since,
            from_value=args.from_value,
            to_value=args.to_value,
        )
    except TimeParseError as exc:
        print(f"codex-token-usage: error: {exc}", file=stderr)
        return 2

    result = scan_codex_usage(_codex_home(args.codex_home), window, now=now)
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2), file=stdout)
    else:
        print(
            render_human(
                result,
                include_daily=not args.no_daily,
                language=args.lang,
            ),
            end="",
            file=stdout,
        )

    if "sessions_directory_missing" in result.warnings:
        return 1
    if args.strict and result.warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
