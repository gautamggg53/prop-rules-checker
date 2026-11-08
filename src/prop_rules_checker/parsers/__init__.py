"""Trade-history parsers and format auto-detection."""

from __future__ import annotations

from pathlib import Path

from ..models import InputError, TradeHistory
from .common import (
    collect_ambiguous_dates,
    get_tz,
    html_rows,
    looks_like_html,
    norm,
    read_csv_rows,
    read_text,
)
from .ctrader import parse_ctrader
from .generic import column_map, parse_generic
from .metatrader import (
    MT5_DEALS_NOT_SUPPORTED,
    _is_mt4_header,
    _is_mt5_deals_header,
    _is_mt5_header,
    parse_mt4,
    parse_mt5,
)
from .tradingview import parse_tradingview, parse_tradingview_paper

FORMATS = {
    "mt4": "MetaTrader 4 account history report (HTML statement, or its table saved as CSV)",
    "mt5": "MetaTrader 5 Positions table (HTML, UTF-16 OK, or CSV). Not the Deals table.",
    "ctrader": "cTrader History tab export (CSV)",
    "tradingview": "TradingView Strategy Tester 'List of trades' CSV",
    "tradingview-paper": "TradingView Paper Trading 'Balance history' CSV (best effort)",
    "generic": "Documented generic CSV (close_time, pnl, ...)",
}


def header_format(header: list[str]) -> str | None:
    """Return the export format a single header row belongs to, or ``mt5-deals``.

    ``mt5-deals`` is not a supported format. Callers turn it into an actionable error.
    """
    h = [norm(x) for x in header]
    if any(x.startswith(("trade #", "trade number")) for x in h):
        return "tradingview"
    if "balance before" in h and any(x.startswith("action") for x in h):
        return "tradingview-paper"
    if any(x.startswith(("opening time", "opening direction", "closing time")) for x in h):
        return "ctrader"
    if _is_mt4_header(header):
        return "mt4"
    if _is_mt5_header(header):
        return "mt5"
    if _is_mt5_deals_header(header):
        return "mt5-deals"
    cmap = column_map(header)
    if "close_time" in cmap and ("pnl" in cmap or "profit" in cmap):
        return "generic"
    return None


def find_table(rows: list[list[str]], *, limit: int = 40) -> tuple[int, str] | None:
    """First row in ``rows`` that is a known header, and the format it names."""
    for i, row in enumerate(rows[:limit]):
        fmt = header_format(row)
        if fmt:
            return i, fmt
    return None


def _unrecognized_csv(rows: list[list[str]]) -> str:
    for row in rows[:40]:
        cmap = column_map(row)
        if not cmap:
            continue
        missing: list[str] = []
        if "close_time" not in cmap and ("pnl" in cmap or "profit" in cmap or "open_time" in cmap):
            missing.append("close_time")
        if "pnl" not in cmap and "profit" not in cmap and "close_time" in cmap:
            missing.append("pnl or profit")
        if missing:
            return (
                "this looks like the generic CSV but is missing "
                + " and ".join(missing)
                + f". Header seen: {', '.join(row[:12])}. "
                "The generic schema needs close_time and pnl (or profit)."
            )
    header = rows[0] if rows else []
    shown = ", ".join(header[:12]) or "(no header)"
    return (
        "could not detect the file format from its header "
        f"({shown}). Supported: MT4 HTML statement (Closed Transactions); "
        "MT5 Positions table as HTML or CSV (not the Deals table, not Excel/XML); "
        "cTrader History CSV; TradingView Strategy Tester list-of-trades CSV; "
        "TradingView paper balance-history CSV; generic CSV with close_time and pnl. "
        f"Force one with --format ({', '.join(FORMATS)})."
    )


def _html_format_error(rows: list[list[str]], low: str) -> InputError:
    if any(_is_mt5_deals_header(r) for r in rows) or any(
        norm(" ".join(c for c in r if c)) == "deals" for r in rows
    ):
        return InputError(MT5_DEALS_NOT_SUPPORTED)
    if "open trades" in low:
        return InputError(
            "HTML has an Open Trades section but no Closed Transactions table. "
            "Open positions are not checked. In MT4 Account History use Save as Report "
            "(or Save as Detailed Report) so the file includes Closed Transactions."
        )
    return InputError(
        "HTML file is not a recognised MT4 statement or MT5 report. "
        "MT4: Account History → Save as Report. "
        "MT5: History, Positions view → Report → HTML. "
        "Deals-only and Excel/XML reports are not supported."
    )


def detect_format(text: str) -> str:
    """Guess the export format from file contents (not the extension)."""
    if looks_like_html(text):
        low = text.lower()
        if "closed transactions" in low:
            return "mt4"
        rows = html_rows(text)
        if any(_is_mt5_header(r) for r in rows):
            return "mt5"
        if any(_is_mt4_header(r) for r in rows):
            return "mt4"
        raise _html_format_error(rows, low)
    rows, _ = read_csv_rows(text)
    found = find_table(rows)
    if found is None:
        raise InputError(_unrecognized_csv(rows))
    _index, fmt = found
    if fmt == "mt5-deals":
        raise InputError(MT5_DEALS_NOT_SUPPORTED)
    return fmt


def _drop_preamble(rows: list[list[str]], fmt_name: str) -> tuple[int, list[list[str]]]:
    """Drop title rows that sit above a recognised header for ``fmt_name``."""
    found = find_table(rows)
    if found and found[0] > 0 and found[1] == fmt_name:
        return found[0], rows[found[0] :]
    return 0, rows


def _ambiguous_date_note(samples: list[str]) -> str:
    shown = samples[0]
    return (
        "Data limit: "
        f"{len(samples)} timestamp(s) like {shown!r} are valid as both day-first and "
        "month-first; they were read day-first (2/3/2026 means 2 March). Pass "
        "--date-format '%m/%d/%Y %H:%M' if the file is month-first."
    )


def load_trades(
    path: str | Path,
    format: str = "auto",
    *,
    source_tz: str = "UTC",
    date_format: str | None = None,
    symbol: str | None = None,
) -> TradeHistory:
    """Load a trade history file.

    ``source_tz`` is used for timestamps without a zone (MetaTrader server time,
    TradingView chart time). ``date_format`` is a ``strptime`` pattern for
    ambiguous dates. ``symbol`` labels trades in exports without a symbol column.
    """
    text = read_text(path)
    if not text.strip():
        raise InputError(f"{path}: the file is empty")
    try:
        fmt_name = detect_format(text) if format == "auto" else format
    except InputError as exc:
        raise InputError(f"{path}: {exc}") from exc
    if fmt_name not in FORMATS:
        raise InputError(f"unknown format {format!r}; choose one of: auto, {', '.join(FORMATS)}")
    tz = get_tz(source_tz)
    src = str(path)
    preamble = 0
    with collect_ambiguous_dates() as ambiguous:
        try:
            if fmt_name in ("mt4", "mt5"):
                is_html = looks_like_html(text)
                if is_html:
                    rows, dec = html_rows(text), False
                else:
                    rows, delim = read_csv_rows(text)
                    dec = delim == ";"
                    preamble, rows = _drop_preamble(rows, fmt_name)
                parser = parse_mt4 if fmt_name == "mt4" else parse_mt5
                history = parser(
                    rows, tz, fmt=date_format, decimal_comma=dec, source=src, is_html=is_html
                )
            else:
                if looks_like_html(text):
                    raise InputError(f"format {fmt_name!r} expects a CSV file, got HTML")
                rows, delim = read_csv_rows(text)
                preamble, rows = _drop_preamble(rows, fmt_name)
                if len(rows) < 2:
                    raise InputError("the file has a header but no data rows")
                dec = delim == ";"
                if fmt_name == "ctrader":
                    history = parse_ctrader(
                        rows, tz, fmt=date_format, decimal_comma=dec, source=src
                    )
                elif fmt_name == "tradingview":
                    history = parse_tradingview(
                        rows, tz, fmt=date_format, decimal_comma=dec, source=src, symbol=symbol
                    )
                elif fmt_name == "tradingview-paper":
                    history = parse_tradingview_paper(
                        rows, tz, fmt=date_format, decimal_comma=dec, source=src
                    )
                else:
                    history = parse_generic(
                        rows, tz, fmt=date_format, decimal_comma=dec, source=src
                    )
        except InputError as exc:
            raise InputError(f"{path} ({fmt_name}): {exc}") from exc
    if preamble:
        history.notes.append(f"Skipped {preamble} leading row(s) before the {fmt_name} header.")
    if ambiguous and date_format is None:
        history.notes.append(_ambiguous_date_note(ambiguous))
    if not history.trades:
        extra = " ".join(n for n in history.notes if n.startswith("Data limit:"))
        detail = f" {extra}" if extra else ""
        raise InputError(f"{path} ({fmt_name}): no closed trades found.{detail}")
    if symbol and fmt_name != "tradingview":
        history.notes.append("--symbol is only used for TradingView strategy exports; ignored.")
    for t in history.trades:
        if t.open_time is not None and t.open_time > t.close_time:
            raise InputError(f"{path}: trade {t.id} closes before it opens")
    if fmt_name in ("mt4", "mt5", "tradingview") and source_tz.upper() in ("UTC", "GMT"):
        history.notes.append(
            f"{fmt_name}: timestamps carry no timezone and were read as UTC; "
            "pass --source-tz (e.g. your broker's server zone) if that is wrong."
        )
    return history


__all__ = ["FORMATS", "detect_format", "load_trades"]
