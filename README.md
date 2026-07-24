# Codex Token Usage

`codex-token-usage` audits token activity recorded in local Codex session logs. It is designed for
API-key users who cannot access the provider's billing dashboard and need a reproducible,
on-machine report.

The scanner excludes history imported from Claude Code while retaining genuine Codex calls made
after an imported thread was continued.

## Why not sum `total_tokens`?

Codex session logs are append-only rollouts, not billing exports:

- `token_count` snapshots can be repeated without new model activity.
- A rollout can contain inherited `session_meta` records; the first record owns the file.
- Imported Claude Code history contains a synthetic token estimate that is not an API call.
- A fork or resumed thread can begin with an existing cumulative value.

The tool counts `last_token_usage` only when the structured cumulative counter advances. Exact
event copies are deduplicated across files. Imported-thread boundaries come from
`external_agent_session_imports.json`, with Codex's imported-session marker used as a fallback and
consistency check.

## Install

Python 3.11 or newer is required. Runtime code uses only the Python standard library.

Install directly from GitHub with `pipx`:

```bash
pipx install git+https://github.com/catchmeee2002/codex-token-usage.git
```

Or install from a clone:

```bash
git clone https://github.com/catchmeee2002/codex-token-usage.git
cd codex-token-usage
python3 -m pip install .
```

## Usage

The default report covers the rolling seven days and includes daily buckets:

```bash
codex-token-usage
```

Select another rolling window:

```bash
codex-token-usage --since 24h
codex-token-usage --since 2w
```

Select an explicit range. A date passed to `--to` includes that entire local day; a datetime is an
exclusive upper bound.

```bash
codex-token-usage \
  --from 2026-07-18 \
  --to 2026-07-25 \
  --timezone Asia/Shanghai
```

Inspect all recorded history or emit machine-readable output:

```bash
codex-token-usage --all
codex-token-usage --since 7d --json
```

Additional controls:

```text
--codex-home PATH  Override CODEX_HOME and ~/.codex discovery.
--no-daily         Hide daily rows in human output.
--strict           Fail when authentication or integrity warnings are present.
```

## Output semantics

- **Total tokens** is `input_tokens + output_tokens`.
- **Cached input** is a subset of input, not an additional amount.
- **Reasoning output** is a subset of output, not an additional amount.
- Root and subagent activity are classified from the first `session_meta` in each rollout.
- JSON output has a stable top-level `schema_version` field, currently `1`.

The current `auth_mode` is reported by reading only that field from `auth.json`. Codex session logs
do not retain the identity of the API key used by each historical request. If keys or login modes
changed during the selected period, the tool cannot split usage by credential. It does not estimate
cost because model pricing and company-pool accounting are not present in local logs.

## Robustness and privacy

The scanner reads a stable prefix of every JSONL file so it can run while Codex is active. It
ignores an unfinished final record, reports malformed interior records, detects cumulative counter
resets, and tolerates unknown fields added by newer Codex versions. `--strict` turns warnings into a
non-zero exit status.

Reports never include API keys, prompts, responses, working directories, session IDs, or source
paths. Message content is inspected only for Codex's exact imported-session marker and is not
retained.

## Development

```bash
python3 -m pip install -e '.[dev]'
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
python3 -m build
```
