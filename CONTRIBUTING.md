# Contributing

Thanks for helping improve `codex-token-usage`. Bug reports, focused feature proposals,
documentation improvements, and tested pull requests are welcome.

## Before opening an issue

- Search existing issues first.
- Include the command you ran, the operating system, Python version, and tool version.
- Remove prompts, responses, API keys, session IDs, file paths, and other private data from logs.
- For security-sensitive reports, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

```bash
git clone https://github.com/catchmeee2002/codex-token-usage.git
cd codex-token-usage
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

On Windows, activate the virtual environment with `.venv\Scripts\activate`.

## Validation

Run the regression suite and build the distributions before submitting a pull request:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m build
```

Behavior changes should include tests. Changes to human-readable output should cover both Chinese
and English when applicable. JSON changes must preserve compatibility or intentionally increment
the top-level schema version.

## Pull requests

- Keep each pull request focused on one problem.
- Explain the user-visible behavior and the validation performed.
- Preserve privacy: reports and fixtures must not contain real prompts, credentials, session IDs,
  or local paths.
- Do not weaken imported-history detection or silently suppress integrity warnings.
- Update public documentation when CLI behavior, supported platforms, or output contracts change.

By participating, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
