# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `prop-rules-check --demo` checks a synthetic history bundled in the install, so a fresh install does not need the `examples/` directory or a trades file. `python -m prop_rules_checker` is the same entry point when the console script is not on `PATH`.
- Text reports print **Closed-trade limits** above the status table (also the JSON field `limitations`). Equity rules with no adverse-excursion data say, on the rule row, that a floating loss would not show.
- Daily-loss breaches and near-misses name the trade at the worst point and the amount over the limit, or the room left.
- Unrecognised files name the export to use: Excel workbooks, an MT5 Deals table, an MT4 Open-Trades-only HTML file, and a generic CSV missing `close_time` or `pnl`.
- Still-open positions listed in an MT4, MT5 or TradingView export are counted in the report. They are still not checked.
- A title row above a known CSV header is skipped. Slash dates that are valid both day-first and month-first stay day-first, and the report says so.

### Fixed

- CSV files that start with Excel's `sep=;` line (common in semicolon-delimited
  exports from European locales) are now read with that delimiter, and the line
  is no longer mistaken for the header.
- Delimiter sniffing ignores commas inside quoted header cells, so a header like
  `"Profit, USD";"Close time"` is split on `;` rather than `,`.

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
