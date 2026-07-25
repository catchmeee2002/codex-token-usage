# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-07-26

### Changed

- Replaced horizontal daily bars with a conventional vertical chart using dates on the x-axis and
  token volume on the y-axis
- Filled missing calendar dates with zero values so spacing remains chronological
- Added automatic multi-day buckets when a selected range is wider than the terminal

## [0.2.0] - 2026-07-26

### Added

- Full-screen terminal dashboard with selectable time ranges and daily bar charts
- Chinese and English text output, CLI help, and interactive UI
- In-UI language switching with the `l` key
- Bilingual project documentation and public contribution templates
- Conditional Windows terminal and timezone support, plus Windows CI coverage

### Changed

- The no-argument command opens the terminal UI when attached to an interactive TTY
- Rolling seven-day text output now clearly states that it is not an all-history report

## [0.1.0] - 2026-07-25

### Added

- Local Codex session-log scanner
- Imported Claude Code history exclusion with continued-thread handling
- Rolling, custom, and all-history time windows
- Human-readable and JSON reports
- Integrity diagnostics, strict mode, tests, packaging, and CI
