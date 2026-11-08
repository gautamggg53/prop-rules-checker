"""MetaTrader 4 and MetaTrader 5 history reports (HTML, or the same table saved as CSV).

MT4: "Save as Report" / "Save as Detailed Report" from the Account History tab
produces an HTML statement whose "Closed Transactions" table has the columns
Ticket, Open Time, Type, Size, Item, Price, S / L, T / P, Close Time, Price,
Commission, Taxes, Swap, Profit.

MT5: History tab -> Report -> HTML produces a "Trade History Report" (usually
UTF-16) whose "Positions" table has Time, Position, Symbol, Type, Volume, Price,
S / L, T / P, Time, Price, Commission, Swap, Profit (the first Time/Price pair is
the open, the second the close).

Times in both are broker *server* time with no zone, so pass ``source_tz``.
"""

from __future__ import annotations

from datetime import tzinfo

from ..models import InputError, Trade, TradeHistory
from .common import norm, parse_datetime, parse_number

_MT4_SECTION_END = ("open trades", "working orders", "summary", "closed p/l")
_MT5_SECTION_END = ("orders", "deals", "open positions", "working orders", "results", "summary")

MT5_DEALS_NOT_SUPPORTED = (
    "this is an MT5 Deals export (one row per fill, not per closed position). "
    "The checker reads the Positions table, which has both an open time and a close time. "
    "In MT5: Toolbox → History, switch the view to Positions, then right-click → Report "
    "and save HTML (or copy that table to CSV). The XML/Excel report is not supported. "
    "A Deals-only file is not reconstructed into positions."
)


def _indices(header: list[str]) -> dict[str, list[int]]:
    idx: dict[str, list[int]] = {}
    for i, h in enumerate(header):
        key = norm(h).replace(" / ", "/").replace(" ", "")
        if key:
            idx.setdefault(key, []).append(i)
    return idx


def _cell(row: list[str], i: int | None) -> str:
    return row[i] if i is not None and i < len(row) else ""


def _pick(idx: dict[str, list[int]], *names: str, occurrence: int = 0) -> int | None:
    for n in names:
        if n in idx and len(idx[n]) > occurrence:
            return idx[n][occurrence]
    return None


def _is_mt4_header(row: list[str]) -> bool:
    keys = _indices(row)
    return "ticket" in keys and "item" in keys and ("size" in keys or "lots" in keys)


def _is_mt5_header(row: list[str]) -> bool:
    keys = _indices(row)
    return (
        "position" in keys
        and "symbol" in keys
        and "volume" in keys
        and len(keys.get("time", [])) >= 2
    )


def _is_mt5_deals_header(row: list[str]) -> bool:
    keys = _indices(row)
    return "deal" in keys and "direction" in keys and "profit" in keys and "position" not in keys


def _count_section_trades(
    rows: list[list[str]], start: tuple[str, ...], stop: tuple[str, ...]
) -> int:
    """Count buy/sell rows in a named HTML section (open trades, open positions)."""
    active = False
    count = 0
    for row in rows:
        joined = norm(" ".join(c for c in row if c))
        if any(joined.startswith(s) for s in start):
            active = True
            continue
        if active and any(joined.startswith(s) for s in stop):
            active = False
            continue
        # MT4 tickets are the first cell; MT5 open-position rows start with a time.
        # A cell that is exactly buy or sell is the type column, not a header.
        if not active or not row:
            continue
        if any(norm(c) in ("buy", "sell") for c in row):
            count += 1
    return count


def _open_position_note(count: int, platform: str) -> str | None:
    if not count:
        return None
    return (
        f"Data limit: the {platform} export lists {count} still-open position(s). "
        "Their floating P/L is not included, so a breach that exists only while they "
        "are open cannot show."
    )


def parse_mt4(
    rows: list[list[str]],
    tz: tzinfo,
    *,
    fmt: str | None = None,
    decimal_comma: bool = False,
    source: str = "",
    is_html: bool = True,
) -> TradeHistory:
    notes: list[str] = []
    trades: list[Trade] = []
    header: dict[str, list[int]] | None = None
    in_closed = not is_html  # a CSV has no section titles
    skipped_balance = 0.0
    skipped_other = 0
    for row in rows:
        first = norm(row[0]) if row else ""
        joined = norm(" ".join(c for c in row if c))
        if is_html and joined.startswith("closed transactions"):
            in_closed = True
            continue
        if is_html and in_closed and any(joined.startswith(s) for s in _MT4_SECTION_END):
            in_closed = False
            continue
        if not in_closed:
            continue
        if _is_mt4_header(row):
            header = _indices(row)
            continue
        if header is None or not first.isdigit():
            continue
        typ = norm(_cell(row, _pick(header, "type")))
        if typ == "balance" or typ == "credit":
            skipped_balance += parse_number(_cell(row, len(row) - 1), field="balance", empty=0.0)
            continue
        if typ not in ("buy", "sell"):
            skipped_other += 1  # cancelled pending orders and similar
            continue
        commission = parse_number(
            _cell(row, _pick(header, "commission")), empty=0.0, decimal_comma=decimal_comma
        )
        taxes = parse_number(
            _cell(row, _pick(header, "taxes")), empty=0.0, decimal_comma=decimal_comma
        )
        swap = parse_number(
            _cell(row, _pick(header, "swap")), empty=0.0, decimal_comma=decimal_comma
        )
        profit = parse_number(
            _cell(row, _pick(header, "profit")),
            field=f"profit of #{first}",
            decimal_comma=decimal_comma,
        )
        trades.append(
            Trade(
                id=row[0],
                symbol=_cell(row, _pick(header, "item", "symbol")).upper(),
                side=typ,
                volume=parse_number(
                    _cell(row, _pick(header, "size", "lots")),
                    field="size",
                    decimal_comma=decimal_comma,
                ),
                open_time=parse_datetime(
                    _cell(row, _pick(header, "opentime")),
                    tz,
                    fmt=fmt,
                    field=f"open time of #{first}",
                ),
                close_time=parse_datetime(
                    _cell(row, _pick(header, "closetime")),
                    tz,
                    fmt=fmt,
                    field=f"close time of #{first}",
                ),
                pnl=round(profit + commission + taxes + swap, 10),
                open_price=parse_number(
                    _cell(row, _pick(header, "price")), empty=0.0, decimal_comma=decimal_comma
                ),
                close_price=parse_number(
                    _cell(row, _pick(header, "price", occurrence=1)),
                    empty=0.0,
                    decimal_comma=decimal_comma,
                ),
                commission=commission + taxes,
                swap=swap,
            )
        )
    if header is None:
        if any(norm(" ".join(c for c in r if c)).startswith("open trades") for r in rows):
            raise InputError(
                "no MT4 'Closed Transactions' table header was found. An Open Trades "
                "section is present, but open positions are not checked. In MT4 Account "
                "History use Save as Report (or Save as Detailed Report) so the file "
                "includes Closed Transactions (Ticket, Open Time, Type, Size, Item, ...)."
            )
        raise InputError(
            "no MT4 'Closed Transactions' table header (Ticket, Open Time, Type, "
            "Size, Item, ...) was found"
        )
    notes.append("MT4: net P/L per trade = Profit + Commission + Taxes + Swap.")
    open_note = _open_position_note(
        _count_section_trades(rows, ("open trades",), ("working orders", "summary", "closed p/l")),
        "MT4",
    )
    if open_note:
        notes.append(open_note)
    if skipped_balance:
        notes.append(
            f"MT4: ignored balance/credit operations totalling {skipped_balance:,.2f} "
            "(deposits are not treated as trading profit)."
        )
    if skipped_other:
        notes.append(f"MT4: skipped {skipped_other} non-trade row(s) such as cancelled orders.")
    return TradeHistory(trades=trades, format="mt4", source=source, notes=notes)


def parse_mt5(
    rows: list[list[str]],
    tz: tzinfo,
    *,
    fmt: str | None = None,
    decimal_comma: bool = False,
    source: str = "",
    is_html: bool = True,
) -> TradeHistory:
    trades: list[Trade] = []
    header: dict[str, list[int]] | None = None
    in_positions = not is_html
    seen_section = False
    for row in rows:
        joined = norm(" ".join(c for c in row if c))
        if is_html and joined == "positions":
            in_positions, seen_section = True, True
            continue
        if is_html and in_positions and header is not None and joined in _MT5_SECTION_END:
            break
        if not in_positions:
            continue
        if _is_mt5_header(row):
            header = _indices(row)
            continue
        if header is None:
            continue
        pos = _cell(row, _pick(header, "position", "ticket"))
        typ = norm(_cell(row, _pick(header, "type")))
        if not pos or typ not in ("buy", "sell"):
            continue
        commission = parse_number(
            _cell(row, _pick(header, "commission")), empty=0.0, decimal_comma=decimal_comma
        )
        swap = parse_number(
            _cell(row, _pick(header, "swap")), empty=0.0, decimal_comma=decimal_comma
        )
        profit = parse_number(
            _cell(row, _pick(header, "profit")),
            field=f"profit of {pos}",
            decimal_comma=decimal_comma,
        )
        trades.append(
            Trade(
                id=pos,
                symbol=_cell(row, _pick(header, "symbol")).upper(),
                side=typ,
                volume=parse_number(
                    _cell(row, _pick(header, "volume")), field="volume", decimal_comma=decimal_comma
                ),
                open_time=parse_datetime(
                    _cell(row, _pick(header, "time")), tz, fmt=fmt, field=f"open time of {pos}"
                ),
                close_time=parse_datetime(
                    _cell(row, _pick(header, "time", occurrence=1)),
                    tz,
                    fmt=fmt,
                    field=f"close time of {pos}",
                ),
                pnl=round(profit + commission + swap, 10),
                open_price=parse_number(
                    _cell(row, _pick(header, "price")), empty=0.0, decimal_comma=decimal_comma
                ),
                close_price=parse_number(
                    _cell(row, _pick(header, "price", occurrence=1)),
                    empty=0.0,
                    decimal_comma=decimal_comma,
                ),
                commission=commission,
                swap=swap,
            )
        )
    if header is None:
        if any(_is_mt5_deals_header(r) for r in rows):
            raise InputError(MT5_DEALS_NOT_SUPPORTED)
        where = "in the 'Positions' section" if seen_section else "(no 'Positions' section found)"
        raise InputError(
            f"no MT5 Positions table header {where}. Save the report from the "
            "History tab with the Positions view as HTML (the Deals table and the "
            "XML/Excel report are not supported)."
        )
    notes = [
        "MT5: net P/L per position = Profit + Commission + Swap (Profit is gross in the "
        "Positions table)."
    ]
    open_note = _open_position_note(
        _count_section_trades(
            rows,
            ("open positions",),
            ("orders", "deals", "working orders", "results", "summary", "positions"),
        ),
        "MT5",
    )
    if open_note:
        notes.append(open_note)
    return TradeHistory(trades=trades, format="mt5", source=source, notes=notes)
