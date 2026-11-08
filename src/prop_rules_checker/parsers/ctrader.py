"""cTrader History tab export (CSV).

Column names follow the cTrader help pages (History tab): ID, Symbol, Opening
direction, Opening time, Closing time, Entry price, Closing price, Closing
quantity, Swap, Commission(s), Gross, Net, Balance. Exports often append the
timezone to time headers, e.g. ``Opening Time (UTC+1)``, and the account currency
to money headers, e.g. ``Net EUR``. Columns can be reordered or hidden by the user,
so they are matched by name, not position.
"""

from __future__ import annotations

import re
from datetime import tzinfo

from ..models import InputError, Trade, TradeHistory
from .common import get_tz, norm, parse_datetime, parse_number


def _find(headers: list[str], *prefixes: str, exclude: tuple[str, ...] = ()) -> int | None:
    for p in prefixes:
        for i, h in enumerate(headers):
            if h.startswith(p) and not any(h.startswith(x) for x in exclude):
                return i
    return None


def _header_tz(header: str, default: tzinfo) -> tzinfo:
    m = re.search(r"\(\s*(utc|gmt)\s*([+-]\d{1,2}(?::?\d{2})?)?\s*\)", header, re.IGNORECASE)
    if not m:
        return default
    return get_tz(m.group(2) or "UTC")


def parse_ctrader(
    rows: list[list[str]],
    tz: tzinfo,
    *,
    fmt: str | None = None,
    decimal_comma: bool = False,
    source: str = "",
) -> TradeHistory:
    headers = [norm(h) for h in rows[0]]
    i_open = _find(headers, "opening time", "open time", "created")
    i_close = _find(headers, "closing time", "close time")
    i_net = _find(headers, "net", exclude=("net usd", "net (usd)"))
    i_net_usd = _find(headers, "net usd", "net (usd)")
    i_gross = _find(headers, "gross", exclude=("gross usd", "gross (usd)"))
    i_comm = _find(headers, "commission")
    i_swap = _find(headers, "swap")
    i_sym = _find(headers, "symbol")
    i_dir = _find(headers, "opening direction", "direction")
    i_qty = _find(headers, "closing quantity", "quantity", "volume", "closing volume")
    i_id = _find(headers, "id", "position id", "position", exclude=("ident",))
    i_entry = _find(headers, "entry price")
    i_exit = _find(headers, "closing price")
    if i_close is None:
        raise InputError(
            "cTrader export has no 'Closing time' column; enable it in the History "
            "tab (right-click a column header) and export again"
        )
    if i_net is None and i_net_usd is None and i_gross is None:
        raise InputError(
            "cTrader export has no Net or Gross column; enable 'Net' in the History "
            "tab and export again"
        )
    notes: list[str] = []
    tz_open = _header_tz(rows[0][i_open], tz) if i_open is not None else tz
    tz_close = _header_tz(rows[0][i_close], tz)
    if tz_close is not tz:
        notes.append(f"cTrader: timezone taken from the column header {rows[0][i_close]!r}.")
    if i_net is None and i_net_usd is not None:
        notes.append("cTrader: using the 'Net USD' column; limits are compared in USD.")
    if i_open is None:
        notes.append(
            "Data limit: cTrader export has no 'Opening time' column, so weekend, "
            "news-at-open and open-lot checks are limited."
        )
    trades: list[Trade] = []
    for n, row in enumerate(rows[1:], start=2):

        def cell(i: int | None, row: list[str] = row) -> str:
            return row[i] if i is not None and i < len(row) else ""

        if not cell(i_close) or not cell(i_sym):
            continue  # totals or blank rows
        comm = parse_number(cell(i_comm), empty=0.0, decimal_comma=decimal_comma)
        swap = parse_number(cell(i_swap), empty=0.0, decimal_comma=decimal_comma)
        if i_net is not None or i_net_usd is not None:
            pnl = parse_number(
                cell(i_net if i_net is not None else i_net_usd),
                field=f"Net on row {n}",
                decimal_comma=decimal_comma,
            )
        else:
            pnl = (
                parse_number(cell(i_gross), field=f"Gross on row {n}", decimal_comma=decimal_comma)
                + comm
                + swap
            )
        side = norm(cell(i_dir))
        trades.append(
            Trade(
                id=cell(i_id) or f"row{n}",
                symbol=cell(i_sym).upper(),
                side="buy" if side.startswith("b") else "sell" if side.startswith("s") else side,
                volume=parse_number(cell(i_qty), empty=0.0, decimal_comma=decimal_comma),
                open_time=(
                    parse_datetime(cell(i_open), tz_open, fmt=fmt, field=f"opening time row {n}")
                    if cell(i_open)
                    else None
                ),
                close_time=parse_datetime(
                    cell(i_close), tz_close, fmt=fmt, field=f"closing time row {n}"
                ),
                pnl=pnl,
                open_price=parse_number(cell(i_entry), empty=0.0, decimal_comma=decimal_comma),
                close_price=parse_number(cell(i_exit), empty=0.0, decimal_comma=decimal_comma),
                commission=comm,
                swap=swap,
            )
        )
    if (
        i_qty is not None
        and "lot"
        not in " ".join(r[i_qty].lower() for r in rows[1:6] if i_qty < len(r)) + headers[i_qty]
    ):
        notes.append(
            "cTrader: quantity column has no 'Lots' unit; lot limits assume it is in "
            "lots (set the History tab to show lots before exporting)."
        )
    return TradeHistory(trades=trades, format="ctrader", source=source, notes=notes)
