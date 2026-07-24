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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-token-usage",
        description=(
            "Audit local Codex token usage while excluding imported Claude Code history."
        ),
    )
    parser.add_argument("--since", metavar="DURATION", help="rolling window such as 24h, 7d, or 2w")
    parser.add_argument("--from", dest="from_value", metavar="ISO", help="inclusive ISO start")
    parser.add_argument(
        "--to",
        dest="to_value",
        metavar="ISO",
        help="exclusive ISO datetime, or an inclusive ISO date",
    )
    parser.add_argument("--all", dest="all_time", action="store_true", help="scan all history")
    parser.add_argument("--timezone", help="IANA timezone used for naive dates and daily buckets")
    parser.add_argument("--codex-home", type=Path, help="override CODEX_HOME")
    parser.add_argument("--json", action="store_true", help="emit stable schema-versioned JSON")
    parser.add_argument("--no-daily", action="store_true", help="hide daily rows in human output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return a non-zero status when any integrity or authentication warning occurs",
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
    parser = build_parser()
    args = parser.parse_args(argv)
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

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
        print(render_human(result, include_daily=not args.no_daily), end="", file=stdout)

    if "sessions_directory_missing" in result.warnings:
        return 1
    if args.strict and result.warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
