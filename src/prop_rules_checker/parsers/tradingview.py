"""TradingView exports.

* ``tradingview``: Strategy Tester -> List of trades -> download CSV. One *entry*
  row and one *exit* row per trade, paired by ``Trade #``. Header names vary by
  version (``Price`` / ``Price USD``, ``Contracts`` / ``Position size (qty)``,
  ``Profit`` / ``Net P&L USD``, ``Drawdown`` / ``Drawdown USD``), so they are
  matched by prefix. The file has no symbol column; pass ``symbol=``.
* ``tradingview-paper``: Paper Trading account -> Balance history CSV with
  ``Time, Balance Before, Balance After, Realized P&L (value), ..., Action``.
  The symbol, side and quantity are parsed from the free-text Action column.
  This layout is documented by third parties only (unverified); rows whose Action
  text is not recognised are kept as balance adjustments.
"""

from __future__ import annotations

import re
from datetime import tzinfo

from ..models import InputError, Trade, TradeHistory
from .common import norm, parse_datetime, parse_number


def _find(
    headers: list[str], prefixes: tuple[str, ...], reject: tuple[str, ...] = ()
) -> int | None:
    for p in prefixes:
        for i, h in enumerate(headers):
            if h.startswith(p) and not any(r in h for r in reject):
                return i
    return None


def parse_tradingview(
    rows: list[list[str]],
    tz: tzinfo,
    *,
    fmt: str | None = None,
    decimal_comma: bool = False,
    source: str = "",
    symbol: str | None = None,
) -> TradeHistory:
    h = [norm(x) for x in rows[0]]
    i_no = _find(h, ("trade #", "trade number", "trade no"))
    i_type = _find(h, ("type",))
    i_time = _find(h, ("date/time", "date and time", "date", "time"))
    i_price = _find(h, ("price",))
    i_qty = _find(
        h,
        (
            "position size (qty)",
            "size (qty)",
            "contracts",
            "quantity",
            "qty",
            "position size",
            "size",
        ),
        reject=("value",),
    )
    i_pnl = _find(h, ("net p&l", "profit", "p&l", "net profit"), reject=("%",))
    i_dd = _find(h, ("drawdown", "adverse excursion"), reject=("%",))
    i_sig = _find(h, ("signal",))
    missing = [
        n
        for n, i in (
            ("Trade #", i_no),
            ("Type", i_type),
            ("Date/Time", i_time),
            ("Profit / Net P&L", i_pnl),
        )
        if i is None
    ]
    if missing:
        raise InputError(
            f"TradingView list-of-trades export is missing column(s): {', '.join(missing)}"
        )
    entries: dict[str, list[str]] = {}
    exits: dict[str, list[str]] = {}
    order: list[str] = []
    for row in rows[1:]:
        if i_no >= len(row) or not row[i_no]:
            continue
        no, typ = row[i_no], norm(row[i_type])
        if no not in order:
            order.append(no)
        if typ.startswith("entry"):
            entries[no] = row
        elif typ.startswith("exit"):
            exits[no] = row
    notes: list[str] = []
    trades: list[Trade] = []
    open_left = 0
    for no in order:
        ex, en = exits.get(no), entries.get(no)
        if ex is None or (i_sig is not None and norm(ex[i_sig]) == "open"):
            open_left += 1
            continue
        typ = norm((en or ex)[i_type])
        mae = None
        if i_dd is not None and ex[i_dd]:
            mae = -abs(parse_number(ex[i_dd], empty=0.0, decimal_comma=decimal_comma))
        trades.append(
            Trade(
                id=no,
                symbol=(symbol or "UNKNOWN").upper(),
                side="buy" if "long" in typ else "sell" if "short" in typ else "",
                volume=parse_number(ex[i_qty], empty=0.0, decimal_comma=decimal_comma)
                if i_qty is not None
                else 0.0,
                open_time=parse_datetime(en[i_time], tz, fmt=fmt, field=f"entry time of #{no}")
                if en
                else None,
                close_time=parse_datetime(ex[i_time], tz, fmt=fmt, field=f"exit time of #{no}"),
                pnl=parse_number(ex[i_pnl], field=f"profit of #{no}", decimal_comma=decimal_comma),
                open_price=parse_number(en[i_price], empty=0.0, decimal_comma=decimal_comma)
                if en and i_price is not None
                else None,
                close_price=parse_number(ex[i_price], empty=0.0, decimal_comma=decimal_comma)
                if i_price is not None
                else None,
                mae=mae,
            )
        )
    if symbol is None:
        notes.append(
            "TradingView: the export has no symbol column; trades are labelled UNKNOWN "
            "(pass --symbol so news events can be matched)."
        )
    if open_left:
        notes.append(
            f"Data limit: skipped {open_left} TradingView trade(s) that were still open. "
            "Their floating P/L is not included."
        )
    notes.append("TradingView: quantities are contracts/units as exported, not necessarily lots.")
    if any(t.mae is not None for t in trades):
        notes.append(
            "TradingView: per-trade Drawdown (adverse excursion) is used to estimate equity lows."
        )
    return TradeHistory(
        trades=trades,
        format="tradingview",
        source=source,
        notes=notes,
        volume_unit="contracts/units",
    )


_ACTION = re.compile(
    r"close\s+(long|short)\s+position\s+for\s+symbol\s+(\S+)\s+at\s+price\s+([\d.,]+)"
    r"\s+for\s+([\d.,]+)\s+units",
    re.IGNORECASE,
)


def parse_tradingview_paper(
    rows: list[list[str]],
    tz: tzinfo,
    *,
    fmt: str | None = None,
    decimal_comma: bool = False,
    source: str = "",
) -> TradeHistory:
    h = [norm(x) for x in rows[0]]
    i_time = _find(h, ("time", "date"))
    i_before = _find(h, ("balance before",))
    i_after = _find(h, ("balance after",))
    i_pnl = _find(h, ("realized p&l (value)", "realized p&l", "realised p&l"), reject=("currency",))
    i_action = _find(h, ("action", "description"))
    if (
        i_time is None
        or i_action is None
        or (i_pnl is None and (i_before is None or i_after is None))
    ):
        raise InputError(
            "TradingView paper balance history needs Time, Action and either "
            "'Realized P&L (value)' or 'Balance Before'/'Balance After' columns"
        )
    trades: list[Trade] = []
    for n, row in enumerate(rows[1:], start=2):
        if i_time >= len(row) or not row[i_time]:
            continue
        if i_pnl is not None and row[i_pnl]:
            pnl = parse_number(row[i_pnl], field=f"P&L row {n}", decimal_comma=decimal_comma)
        else:
            pnl = parse_number(row[i_after], field=f"Balance After row {n}") - parse_number(
                row[i_before], field=f"Balance Before row {n}"
            )
        action = row[i_action] if i_action < len(row) else ""
        m = _ACTION.match(action.strip())
        when = parse_datetime(row[i_time], tz, fmt=fmt, field=f"time row {n}")
        if m:
            sym = m.group(2).split(":")[-1].upper()
            trades.append(
                Trade(
                    id=f"row{n}",
                    symbol=sym,
                    side="buy" if m.group(1).lower() == "long" else "sell",
                    volume=parse_number(m.group(4)),
                    open_time=None,
                    close_time=when,
                    pnl=pnl,
                    close_price=parse_number(m.group(3)),
                )
            )
        else:
            trades.append(
                Trade(
                    id=f"row{n}",
                    symbol="",
                    side="",
                    volume=0.0,
                    open_time=None,
                    close_time=when,
                    pnl=pnl,
                    kind="adjustment",
                )
            )
    notes = [
        "TradingView paper: format is not officially documented; parsed from the Action text.",
        "Data limit: TradingView paper exports no open times, so weekend-holding, news-at-open "
        "and open-lot checks cannot be evaluated; minimum trading days are counted by close date.",
        "TradingView paper: quantities are units, not lots.",
    ]
    return TradeHistory(
        trades=trades, format="tradingview-paper", source=source, notes=notes, volume_unit="units"
    )
