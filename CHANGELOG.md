# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- CSV files that start with Excel's `sep=;` line (common in semicolon-delimited
  exports from European locales) are now read with that delimiter, and the line
  is no longer mistaken for the header.
- Delimiter sniffing ignores commas inside quoted header cells, so a header like
  `"Profit, USD";"Close time"` is split on `;` rather than `,`.
- Numbers like `0,125` or `-0,500` (decimal comma, zero integer part) are read
  as 0.125 and -0.5 even when the file isn't detected as decimal-comma, e.g. a
  tab-delimited export. Previously they were taken as thousands grouping, so a
  `0,100` lot size became 100 lots.
- Amounts with more than one dot used as thousands separators and no decimal
  part, such as `1.234.567` or `-1.250.000` (common in German and Italian
  exports), are read as 1234567 and -1250000 instead of failing with
  "expected a number". Misgrouped values like `1.23.456` are still rejected.
- Rule files with `.nan`, `.inf` or `-.inf` (YAML) or `NaN`/`Infinity` (JSON)
  as a number are now rejected with "must be a finite number". Before, they
  passed validation: a NaN daily loss limit crashed with a traceback, a NaN
  starting balance printed "nan" with every rule PASS, and an infinite limit
  silently passed everything.

## [0.1.0] - 2026-11-03

First public release.

### Added
- Rule engine with nine rule types: daily loss (balance or approximated equity,
  initial or day-start reference, configurable reset time and timezone), static
  max drawdown, trailing drawdown on closed balance with optional lock, profit
  target progress, consistency (best day as % of net profit or of winning days),
  minimum trading days, news-trading window (user-supplied events file), weekend
  holding (configurable timezone and Friday close / Sunday open) and lot size
  (per trade and total open lots).
- Near-miss warnings at a configurable fraction of each limit (`--warn-at`, default 0.8).
- Parsers with auto-detection for MT4 HTML statements, MT5 HTML reports (UTF-16),
  the same MT4/MT5 tables saved as CSV, cTrader History CSV, TradingView Strategy
  Tester "List of trades" CSV, TradingView Paper Trading balance history CSV
  (best effort) and a documented generic CSV.
- YAML/JSON rule sets validated against a published JSON Schema, plus three
  illustrative example presets.
- `prop-rules-check` CLI with text and JSON output and exit codes 0/1/2.
- Python API: `load_trades`, `load_rules`, `load_news`, `check` -> `Report`.
