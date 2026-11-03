"""Trade-history parsers and format auto-detection."""

from __future__ import annotations

from pathlib import Path

from ..models import InputError, TradeHistory
from .common import get_tz, html_rows, looks_like_html, norm, read_csv_rows, read_text
from .ctrader import parse_ctrader
from .generic import column_map, parse_generic
from .metatrader import _is_mt4_header, _is_mt5_header, parse_mt4, parse_mt5
from .tradingview import parse_tradingview, parse_tradingview_paper

FORMATS = {
    "mt4": "MetaTrader 4 account history report (HTML statement, or its table saved as CSV)",
    "mt5": "MetaTrader 5 history report, Positions table (HTML, UTF-16 OK, or CSV)",
    "ctrader": "cTrader History tab export (CSV)",
    "tradingview": "TradingView Strategy Tester 'List of trades' CSV",
    "tradingview-paper": "TradingView Paper Trading 'Balance history' CSV (best effort)",
    "generic": "Documented generic CSV (close_time, pnl, ...)",
}


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
        raise InputError("HTML file is not a recognised MT4 statement or MT5 report")
    rows, _ = read_csv_rows(text)
    header = rows[0]
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
    cmap = column_map(header)
    if "close_time" in cmap and ("pnl" in cmap or "profit" in cmap):
        return "generic"
    raise InputError(
        "could not detect the file format from its header "
        f"({', '.join(header[:12])}). Use --format; supported: {', '.join(FORMATS)}"
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
    fmt_name = detect_format(text) if format == "auto" else format
    if fmt_name not in FORMATS:
        raise InputError(f"unknown format {format!r}; choose one of: auto, {', '.join(FORMATS)}")
    tz = get_tz(source_tz)
    src = str(path)
    try:
        if fmt_name in ("mt4", "mt5"):
            is_html = looks_like_html(text)
            if is_html:
                rows, dec = html_rows(text), False
            else:
                rows, delim = read_csv_rows(text)
                dec = delim == ";"
            parser = parse_mt4 if fmt_name == "mt4" else parse_mt5
            history = parser(
                rows, tz, fmt=date_format, decimal_comma=dec, source=src, is_html=is_html
            )
        else:
            if looks_like_html(text):
                raise InputError(f"format {fmt_name!r} expects a CSV file, got HTML")
            rows, delim = read_csv_rows(text)
            if len(rows) < 2:
                raise InputError("the file has a header but no data rows")
            dec = delim == ";"
            if fmt_name == "ctrader":
                history = parse_ctrader(rows, tz, fmt=date_format, decimal_comma=dec, source=src)
            elif fmt_name == "tradingview":
                history = parse_tradingview(
                    rows, tz, fmt=date_format, decimal_comma=dec, source=src, symbol=symbol
                )
            elif fmt_name == "tradingview-paper":
                history = parse_tradingview_paper(
                    rows, tz, fmt=date_format, decimal_comma=dec, source=src
                )
            else:
                history = parse_generic(rows, tz, fmt=date_format, decimal_comma=dec, source=src)
    except InputError as exc:
        raise InputError(f"{path} ({fmt_name}): {exc}") from exc
    if not history.trades:
        raise InputError(f"{path} ({fmt_name}): no closed trades found")
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
