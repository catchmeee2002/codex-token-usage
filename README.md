# Codex Token Usage

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/catchmeee2002/codex-token-usage/actions/workflows/ci.yml/badge.svg)](https://github.com/catchmeee2002/codex-token-usage/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Audit and visualize token activity recorded in local Codex session logs. The project provides a
bilingual terminal dashboard, script-friendly text and JSON reports, rolling or custom time ranges,
and import-aware counting that excludes historical Claude Code sessions without losing genuine
Codex usage after an imported thread is continued.

> This is an independent community project and is not affiliated with or endorsed by OpenAI.

## Features

- Full-screen terminal UI with Chinese and English interfaces
- Press `l` in the UI to switch languages instantly
- Last 24 hours, last 7 days, last 30 days, all history, and custom date ranges
- Conventional daily charts with dates on the x-axis, tokens on the y-axis, and partial-day markers
- Human-readable Chinese or English text output
- Stable JSON output with `schema_version: 1`
- Root and subagent usage breakdowns
- Structured exclusion of imported Claude Code history
- Duplicate-snapshot handling and explicit integrity warnings
- No prompts, responses, API keys, session IDs, or source paths in reports

## Installation

Python 3.11 or newer is required.

Install directly from GitHub with [`pipx`](https://pipx.pypa.io/):

```bash
pipx install git+https://github.com/catchmeee2002/codex-token-usage.git
```

Or install from a clone:

```bash
git clone https://github.com/catchmeee2002/codex-token-usage.git
cd codex-token-usage
python3 -m pip install .
```

The runtime uses only the Python standard library on Unix-like systems. Windows installs
`windows-curses` and the IANA `tzdata` package automatically.

## Quick start

Open the interactive dashboard:

```bash
codex-token-usage
```

Controls:

| Key | Action |
|---|---|
| `↑` / `↓` or `j` / `k` | Select a time range |
| `Enter` | Apply the selected range |
| `r` | Refresh the current report |
| `l` | Switch between Chinese and English |
| `q` or `Esc` | Exit |

Start the UI in English explicitly:

```bash
codex-token-usage --ui --lang en
```

## Text and JSON reports

Passing a report option uses non-interactive text mode. Without a time option, text mode covers
only the rolling last seven days and clearly labels that scope.

```bash
# Chinese text, rolling last seven days
codex-token-usage --text

# English text
codex-token-usage --text --lang en

# All recorded history
codex-token-usage --all

# Other rolling windows
codex-token-usage --since 24h
codex-token-usage --since 2w

# Inclusive local dates
codex-token-usage \
  --from 2026-07-18 \
  --to 2026-07-25 \
  --timezone Asia/Shanghai

# Machine-readable output
codex-token-usage --all --json
```

Important options:

| Option | Purpose |
|---|---|
| `--ui` | Open the full-screen terminal UI |
| `--text` | Force non-interactive text output |
| `--lang {zh,en}` | Select the initial UI or text language |
| `--all` | Scan all recorded history |
| `--since DURATION` | Select a rolling window such as `24h`, `7d`, or `2w` |
| `--from ISO` / `--to ISO` | Select a custom range |
| `--timezone IANA` | Set the timezone for dates and daily buckets |
| `--json` | Emit stable machine-readable output |
| `--no-daily` | Hide daily rows in text output |
| `--strict` | Return non-zero when integrity or authentication warnings occur |
| `--codex-home PATH` | Override `CODEX_HOME` and `~/.codex` discovery |

## How counting works

Codex rollout logs are append-only activity records, not billing exports. Summing every
`total_tokens` value would overcount because snapshots can repeat, resumed threads can inherit an
existing cumulative value, and imported histories can include synthetic estimates.

The scanner therefore:

1. Reads the first `session_meta` record as the owner of each rollout file.
2. Counts `last_token_usage` only when the structured cumulative counter advances.
3. Deduplicates exact event copies across files.
4. Uses `external_agent_session_imports.json` and Codex's imported-session marker to exclude
   pre-import history.
5. Continues counting genuine Codex calls made after an imported thread is resumed.

`total_tokens` means `input_tokens + output_tokens`. Cached input is a subset of input, and
reasoning output is a subset of output.

## Limitations

- Local session logs are usage evidence, not a provider billing statement.
- Historical logs do not identify which API key produced each request.
- The tool does not estimate cost because pricing and organization-level accounting are not stored
  in local logs.

## Development

```bash
python3 -m pip install -e '.[dev]'
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
python3 -m build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Security issues should follow
[SECURITY.md](SECURITY.md). Project changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
