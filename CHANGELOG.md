# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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
