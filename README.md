# prop-rules-checker

Check a trading account's history against **prop-firm style rules** and get a
clear list of **violations and near-misses**: daily loss, static and trailing
drawdown, profit target, consistency, minimum trading days, news-trading windows,
weekend holding and lot size.

Evaluation ("challenge") and funded accounts are usually lost on a rule, not on
the strategy: a daily loss limit counted from a different reset time than you
assumed, a trailing drawdown that follows your closed-balance high, one big day
breaking a consistency rule, a position held over the weekend. Trading platforms
don't check these for you. This tool reads the history export you already have,
applies a rule file you control, and tells you exactly which trade broke (or
nearly broke) which rule, and what it had to assume to decide.

- Reads **MT4, MT5, cTrader, TradingView** exports and a simple **generic CSV**, with auto-detection.
- Rules live in editable **YAML/JSON** files validated against a JSON Schema.
- **Near-miss warnings** at a configurable fraction of each limit (default 80%).
- **States its assumptions** in every report (e.g. when equity limits can only be approximated).
- CLI with text or JSON output and CI-friendly exit codes, plus a small Python API.
- Python 3.10+, one runtime dependency (PyYAML). MIT licensed.

> **Not financial advice. Not affiliated with, endorsed by, or describing any prop firm.**
> The bundled presets are illustrative examples, not any firm's rules. Firms change
> their terms and word them differently; always write your rule file from your own
> account's current written rules, and treat the output as a check, not a guarantee.

## Install

Not on PyPI yet. Install from source:

```bash
git clone https://github.com/<owner>/prop-rules-checker
cd prop-rules-checker
pip install .
```

## Quickstart

```bash
prop-rules-check examples/sample-trades.csv --rules example-1step-trailing
```

Actual output (the sample file is synthetic):

```text
Rule set: Example 1-step trailing challenge (illustrative, not a real firm)
Trades:   8 (generic, 2026-04-06 to 2026-04-16 UTC)
Balance:  50,000.00 USD -> 51,800.00 USD (net +1,800.00)

RULE                    STATUS   DETAIL
Daily loss limit        WARN     worst day 2026-04-08: 1,500.00 USD of 1,584.00 USD (94.7%)
Trailing drawdown       PASS     high-water 53,200.00 USD, current floor 50,000.00 USD, locked at 50,000.00 USD (max 50.0% used)
Profit target           PENDING  1,800.00 USD of 5,000.00 USD (36.0%)
Consistency (best day)  FAIL     best day 2026-04-07 = 1,600.00 USD, 88.9% of net profit 1,800.00 USD (max 40.0%)
Minimum trading days    PASS     7 trading day(s), minimum 3
Weekend holding         FAIL     1 trade(s) held over a weekend
Lot size                FAIL     largest trade 6 lots (max 5); peak open 7 lots (max 10)

Findings:
  [WARN] Daily loss limit: 2026-04-08: down 1,500.00 USD from the day's start balance of 52,800.00 USD; limit 1,584.00 USD (94.7% used)
  [WARN] Daily loss limit: 2026-04-16: down 1,400.00 USD from the day's start balance of 53,200.00 USD; limit 1,596.00 USD (87.7% used)
  [FAIL] Consistency (best day): best day 2026-04-07 = 1,600.00 USD, 88.9% of net profit 1,800.00 USD (max 40.0%); about 2,200.00 USD more profit on other days would bring it within the limit
  [FAIL] Weekend holding: trade E5 (EURUSD) was open over the weekend of 2026-04-10 (market close 17:00 America/New_York)
  [WARN] Lot size: trade E4 (USDJPY) 4 lots vs max 5
  [FAIL] Lot size: trade E6 (NAS100) 6 lots vs max 5

Assumptions and limitations:
  - Balance starts at 50,000.00 USD (from the rule set) and moves only with closed-trade P/L; deposits, withdrawals and positions still open at export time are not included.
  - A trading day runs from 17:00 to 17:00 in America/New_York and is labelled with the date it ends on; each trade's P/L counts on the day it closed.
  - Touching a limit exactly is a warning; only going beyond it is a violation.

Result: 3 violation(s), 1 near-miss warning(s). Check your firm's current rules; this is not advice.
```

The exit code was `1` (violations found).

A MetaTrader 4 statement with a news calendar, as JSON:

```bash
prop-rules-check tests/fixtures/synthetic_mt4_statement.htm \
  --rules example-2step-challenge --news tests/fixtures/synthetic_news_events.csv --json
```

Excerpt of the actual output:

```json
{
  "status": "fail",
  "violations": 1,
  "warnings": 1,
  "net_pnl": -1454.85,
  "results": [
    ...
    {
      "rule": "news_trading",
      "status": "fail",
      "findings": [
        {
          "status": "fail",
          "message": "trade 1000007 (EURUSD) opened 1 min before US CPI (synthetic) at 2026-03-05 13:30 UTC",
          "time": "2026-03-05T13:29:00+00:00",
          "trade_ids": ["1000007"]
        }
      ]
    }
  ]
}
```

### CLI reference

```text
prop-rules-check TRADES --rules RULES [options]

  -r, --rules RULES      YAML/JSON rule file, or a bundled preset name
  -f, --format FORMAT    auto (default), mt4, mt5, ctrader, tradingview,
                         tradingview-paper, generic
  --json                 JSON report instead of text
  --warn-at FRACTION     near-miss threshold, e.g. 0.8 (or 80) = warn at 80% of a limit
  --news CSV             news events file for the news-trading rule
  --news-tz TZ           zone for naive times in the news file (default UTC)
  --source-tz TZ         zone for naive timestamps in the trade file (default UTC);
                         set this to your MT4/MT5 broker's server zone
  --date-format FMT      strptime pattern for ambiguous dates, e.g. "%m/%d/%Y %H:%M"
  --symbol SYMBOL        symbol for exports that have none (TradingView strategy)
  --list-presets / --list-formats / --version
```

Exit codes: **0** no violations (warnings allowed), **1** at least one violation,
**2** input error (unreadable file, unknown format, invalid rule set).

### Python API

```python
from prop_rules_checker import check, load_news, load_rules, load_trades, Status

trades = load_trades("history.htm", source_tz="Europe/Athens")  # format auto-detected
rules = load_rules("my-account.yaml")  # or a preset name
report = check(trades, rules, news=load_news("calendar.csv"), warn_at=0.8)

for result in report.results:
    print(result.rule, result.status.value, result.summary)
if report.has_violations:
    print(report.to_json())
```

`check()` also accepts a plain list of `Trade` objects.

## Rule files

```yaml
# my-account.yaml: copy a preset (src/prop_rules_checker/presets/) and edit it
name: "My account"
account:
  initial_balance: 100000
  currency: USD
day_reset:
  timezone: Europe/Prague   # IANA zone the firm's day resets in
  time: "00:00"             # HH:MM; e.g. "17:00" with America/New_York
warn_at: 0.8                # optional, overridden by --warn-at
rules:
  daily_loss:        {limit_pct: 5, reference: initial_balance, measure: balance}
  max_drawdown:      {limit_pct: 10, measure: balance}
  trailing_drawdown: {limit_amount: 3000, lock_at: initial_balance}
  profit_target:     {target_pct: 8}
  consistency:       {max_best_day_pct: 40, denominator: net_profit}
  min_trading_days:  {days: 4, count_by: open}
  news_trading:      {minutes_before: 2, minutes_after: 2, impacts: [high], hold_through: warn}
  weekend_holding:   {allowed: false, timezone: UTC, friday_close: "22:00", sunday_open: "22:00"}
  lot_size:          {max_lots_per_trade: 10, max_open_lots: 20}
```

Include only the rules that apply. Unknown keys and bad values are rejected with
a message pointing at the exact key. The schema is in
[`schema/rules.schema.json`](schema/rules.schema.json) (usable for editor
autocompletion). Bundled examples, all **illustrative only**:

| Preset | Shows |
| --- | --- |
| `example-2step-challenge` | static 10% max loss, 5% daily loss on equity, 8% target, 4 days, news window |
| `example-1step-trailing` | 6% trailing drawdown locking at the start balance, 17:00 New York day, consistency, weekend rule |
| `example-funded-account` (JSON) | fixed-amount limits, consistency over winning days, open-lot cap |

## Rule reference

How each rule is evaluated. "Balance" means the starting balance from the rule
file plus the net P/L of closed trades in close-time order.

**Statuses:** `FAIL` (limit exceeded), `WARN` (used at least `warn_at` of a limit,
or touched it exactly), `PENDING` (objective not reached yet), `INFO` (not
applicable), `SKIPPED` (data missing), `PASS`.

| Rule | Options | How it is checked |
| --- | --- | --- |
| `daily_loss` | `limit_pct` or `limit_amount`; `reference`: `initial_balance` \| `day_start_balance`; `measure`: `balance` \| `equity` | For each trading day: start balance = balance at the day reset; loss = start minus the lowest balance (or estimated equity) during the day. Profit earlier in the day does not extend the limit; the low point is what counts. |
| `max_drawdown` | `limit_pct` (of initial) or `limit_amount`; `measure` | Static floor = initial balance - limit. FAIL if any balance/equity point goes below it. |
| `trailing_drawdown` | `limit_pct`/`limit_amount`; `lock_at`: `initial_balance` \| number \| null; `measure` | Floor = highest **closed** balance so far - limit. With `lock_at`, the floor stops rising once it reaches that level. Each point is checked against the floor in force before that close. |
| `profit_target` | `target_pct` or `target_amount` | PASS if final balance - initial >= target, else PENDING with progress; notes if the target was reached earlier and then given back. |
| `consistency` | `max_best_day_pct`; `denominator`: `net_profit` \| `positive_days` | Best day's P/L as a share of net profit (losing days reduce it) or of the sum of winning days. INFO when there is no profit. On FAIL, reports roughly how much more profit on other days would bring it within the limit. |
| `min_trading_days` | `days`; `count_by`: `open` \| `close` \| `any` | Distinct trading days with a trade opened (or closed/either). Balance adjustments don't count. PENDING until met. |
| `news_trading` | `minutes_before`, `minutes_after`, `impacts`, `check`: [`open`,`close`], `hold_through`: `forbid` \| `warn` \| `allow`, `warn_buffer_minutes` | FAIL if a checked open/close time falls in [event - before, event + after] for an event that applies to the symbol. Positions held across the whole window get `hold_through`. Optional buffer gives WARN just outside the window. SKIPPED without `--news`. |
| `weekend_holding` | `allowed`, `timezone`, `friday_close`, `sunday_open` (HH:MM), `warn_within_minutes`, `exempt_symbols` | FAIL if a position is open at any time between Friday close and Sunday open in that zone (including ones opened during the weekend). WARN if closed within N minutes before the Friday close. |
| `lot_size` | `max_lots_per_trade`, `max_open_lots` | Per-trade volume, and the peak sum of volumes open at the same time (a close and an open at the same instant don't overlap). |

### Assumptions and limitations (read these)

- **Closed-trade data cannot see intraday equity.** History exports list closed
  positions, not tick-by-tick equity. With `measure: equity`:
  - if the export has per-trade adverse excursion (TradingView `Drawdown`, or an
    `mae` column in the generic CSV), equity is **estimated** at each close as
    balance plus the worst excursion of every position open at that moment,
    assumed to coincide (conservative: it can over-flag but should not under-flag
    those positions);
  - otherwise it falls back to closed balance and the report says plainly that a
    floating-loss breach **would not show**. Rules using equity are marked `*`.
- **Day attribution:** a trade's P/L counts on the trading day it **closed**. A
  session that starts at or after 12:00 (e.g. 17:00 New York) is labelled with
  the date it ends on. DST is handled through IANA zones.
- **Timezones:** MT4/MT5 and TradingView timestamps carry no zone. They are read
  as `--source-tz` (default UTC), and the report reminds you. cTrader headers such
  as `Opening Time (UTC+2)` are honoured automatically.
- **Balance:** starts at `account.initial_balance`. Deposits/withdrawals in the
  export are ignored (and reported), and positions still open at export time are
  not included.
- **Net P/L:** commission, swap and taxes are added to gross profit where the
  export reports them separately (MT4, MT5); cTrader's `Net` column is used as is.
- **Exactly at a limit** is a WARN, not a FAIL. If your firm treats touching the
  limit as a breach, lower the limit by one cent in your rule file.
- **Lots:** TradingView exports contracts/units, not lots; the report notes the unit.
- Firms differ on details this tool does not model yet (e.g. "daily loss is
  relative to max(balance, equity) at reset", partial-close accounting, hedged
  positions, payout-specific rules). See the roadmap.

## Supported formats

The format is detected from the file contents; override with `--format`.
Columns are matched **by name**, so reordered or extra columns are fine.

| `--format` | Export | Columns used | Verification status |
| --- | --- | --- | --- |
| `mt4` | MT4 Terminal > Account History > *Save as Report* / *Save as Detailed Report* (HTML), or that table as CSV | Closed Transactions: Ticket, Open Time, Type, Size, Item, Price, S / L, T / P, Close Time, Price, Commission, Taxes, Swap, Profit | Column list checked against the official [MT4 help](https://www.metatrader4.com/en/trading-platform/help/overview/terminal/terminal_account_history) and several journal-importer docs. **Not tested against a real statement file**; fixture is synthetic. |
| `mt5` | MT5 Toolbox > History (Positions view) > *Report* > HTML (UTF-16 handled), or that table as CSV | Positions: Time, Position, Symbol, Type, Volume, Price, S / L, T / P, Time, Price, Commission, Swap, Profit | Column list and "Profit is gross" from third-party importer docs (no official MetaQuotes page found). **Not tested against a real report**. The XML/Excel report is not supported. |
| `ctrader` | cTrader History tab > export / Statement saved as CSV | ID, Symbol, Opening direction, Opening/Closing time, Entry/Closing price, Closing quantity, Swap, Commission(s), Gross, Net | Column names from the official [cTrader help](https://help.ctrader.com/ctrader/trading/history/). Exact CSV details (date format, `(UTC+x)` header suffix, currency suffix like `Net EUR`) are from third-party docs and **unverified**; dates are read day-first. Enable lots for quantities. |
| `tradingview` | TradingView Strategy Tester > List of trades > download CSV | Trade #, Type (Entry/Exit long/short), Date/Time, Price, size (qty/Contracts), Net P&L/Profit, Drawdown | Columns per the official [Pine Script docs](https://www.tradingview.com/pine-script-docs/concepts/strategies/) and third-party docs; current (`Net P&L USD`) and older (`Profit`) headers both handled. No symbol column: use `--symbol`. |
| `tradingview-paper` | TradingView Paper Trading > Balance history CSV | Time, Balance Before/After, Realized P&L, Action | **Best effort / unverified**: only third-party descriptions found. Symbol and side are parsed from the Action text; there are no open times, so weekend, news-at-open and open-lot checks can't run (reported as such). |
| `generic` | Your own CSV | see below | Documented here; fully tested. |

Not supported yet: MT5 XML report, MT5 Deals-only reports, Match-Trader,
DXtrade, TradeLocker, NinjaTrader, Rithmic/Tradovate. Exports from those can be
converted to the generic CSV.

If a parser gets your file wrong, please open a "New platform / export format"
issue with an anonymised header and a few rows.

### Generic CSV

```csv
id,symbol,side,volume,open_time,close_time,pnl,commission,swap,mae
T1,EURUSD,buy,1.0,2026-03-02T09:00:00Z,2026-03-02T11:00:00Z,300.00,-7,0,-150
```

| Column | Required | Meaning |
| --- | --- | --- |
| `close_time` | yes | ISO 8601 (with offset or `Z`), or naive in `--source-tz` |
| `pnl` | yes\* | **net** realised P/L in account currency |
| `profit` | \* | gross P/L; used if `pnl` is absent, with `commission` and `swap` added |
| `open_time` | recommended | needed for weekend, news-at-open, open lots, `count_by: open` |
| `id`, `symbol`, `side` (buy/sell/long/short), `volume` (lots) | optional | |
| `commission`, `swap` | optional | signed (costs negative) |
| `mae` | optional | worst floating P/L during the trade; enables equity estimates |
| `kind` | optional | `trade` (default) or `adjustment` (fees etc.: affect balance, not trade counts) |

Lines beginning with `#` are comments. Semicolon-delimited files use decimal commas.

### News events CSV

```csv
time,currency,impact,title,symbols
2026-03-05T13:30:00Z,USD,high,US CPI,
2026-03-05T15:30:00Z,,high,Oil inventories,USOIL|UKOIL
```

An event with `symbols` applies to those symbols (prefix match, so `USOIL.cash`
matches); otherwise with `currency` to symbols containing that code (`USD`
matches `EURUSD` and `XAUUSD`); with neither, to every symbol. You supply the
calendar; none is bundled or fetched.

## Development

```bash
pip install -e ".[dev]"
pytest --cov
ruff check . && ruff format --check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- Verify the MT4/MT5/cTrader parsers against real (anonymised) exports from users.
- MT5 Deals table and XML report; Match-Trader, DXtrade, TradeLocker CSV.
- Daily loss relative to max(balance, equity) at reset; intraday equity from
  tick or bar data, for exact equity limits.
- Partial closes and hedged positions as one position; per-symbol lot limits.
- Rules for payout stages (e.g. minimum profitable days, max single-trade share).
- HTML report output.

## License

MIT © 2026 Gautam Goyal. See [LICENSE](LICENSE).
