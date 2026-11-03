"""The documented generic CSV schema (see README, "Generic CSV").

Required columns: ``close_time`` and ``pnl`` (net) *or* ``profit`` (gross, to
which ``commission`` and ``swap`` are added). Optional: ``id``, ``symbol``,
``side``, ``volume``, ``open_time``, ``open_price``, ``close_price``,
``commission``, ``swap``, ``mae``. Header names are case-insensitive. Lines that
start with ``#`` are comments.
"""

from __future__ import annotations

from datetime import tzinfo

from ..models import InputError, Trade, TradeHistory
from .common import norm, parse_datetime, parse_number

ALIASES = {
    "id": ("id", "ticket", "trade_id", "position_id"),
    "symbol": ("symbol", "instrument", "ticker"),
    "side": ("side", "direction", "type"),
    "volume": ("volume", "lots", "size", "quantity", "qty"),
    "open_time": ("open_time", "entry_time", "opened_at"),
    "close_time": ("close_time", "exit_time", "closed_at"),
    "open_price": ("open_price", "entry_price"),
    "close_price": ("close_price", "exit_price"),
    "pnl": ("pnl", "net_pnl", "net_profit", "net"),
    "profit": ("profit", "gross_pnl", "gross_profit", "gross"),
    "commission": ("commission", "commissions", "fee", "fees"),
    "swap": ("swap", "swaps", "rollover"),
    "mae": ("mae", "max_adverse_excursion", "drawdown"),
    "kind": ("kind",),
}


def column_map(header: list[str]) -> dict[str, int]:
    cols = [norm(h).replace(" ", "_") for h in header]
    out: dict[str, int] = {}
    for key, names in ALIASES.items():
        for name in names:
            if name in cols:
                out[key] = cols.index(name)
                break
    return out


def parse_generic(
    rows: list[list[str]],
    tz: tzinfo,
    *,
    fmt: str | None = None,
    decimal_comma: bool = False,
    source: str = "",
) -> TradeHistory:
    cmap = column_map(rows[0])
    if "close_time" not in cmap or ("pnl" not in cmap and "profit" not in cmap):
        raise InputError(
            "generic CSV needs at least 'close_time' and 'pnl' (or 'profit') "
            f"columns; found: {', '.join(rows[0])}"
        )
    trades: list[Trade] = []
    for n, row in enumerate(rows[1:], start=2):

        def get(key: str, row: list[str] = row) -> str:
            i = cmap.get(key)
            return row[i] if i is not None and i < len(row) else ""

        def num(key: str, n: int = n) -> float:
            return parse_number(
                get(key), field=f"{key} on row {n}", empty=0.0, decimal_comma=decimal_comma
            )

        commission, swap = num("commission"), num("swap")
        if get("pnl"):
            pnl = parse_number(get("pnl"), field=f"pnl on row {n}", decimal_comma=decimal_comma)
        else:
            pnl = (
                parse_number(
                    get("profit"), field=f"pnl/profit on row {n}", decimal_comma=decimal_comma
                )
                + commission
                + swap
            )
        side = norm(get("side"))
        kind = norm(get("kind")) or "trade"
        if kind not in ("trade", "adjustment"):
            raise InputError(f"kind on row {n} must be 'trade' or 'adjustment', got {kind!r}")
        trades.append(
            Trade(
                id=get("id") or f"row{n}",
                symbol=get("symbol").upper(),
                side="buy"
                if side in ("buy", "long", "b")
                else "sell"
                if side in ("sell", "short", "s")
                else side,
                volume=num("volume"),
                open_time=parse_datetime(get("open_time"), tz, fmt=fmt, field=f"open_time row {n}")
                if get("open_time")
                else None,
                close_time=parse_datetime(
                    get("close_time"), tz, fmt=fmt, field=f"close_time row {n}"
                ),
                pnl=pnl,
                open_price=num("open_price") if get("open_price") else None,
                close_price=num("close_price") if get("close_price") else None,
                commission=commission,
                swap=swap,
                mae=-abs(num("mae")) if get("mae") else None,
                kind=kind,
            )
        )
    return TradeHistory(trades=trades, format="generic", source=source)
