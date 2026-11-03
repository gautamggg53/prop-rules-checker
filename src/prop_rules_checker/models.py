"""Core data types shared by the parsers, the rule engine and the report."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime


class InputError(ValueError):
    """An input file (trades, rules or news events) could not be read or is invalid."""


@dataclass(frozen=True)
class Trade:
    """One closed position (or a balance adjustment such as a commission charge).

    All datetimes are timezone-aware and normalised to UTC.
    ``pnl`` is the *net* realised result in account currency, i.e. it already
    includes commission, swap and taxes where the export reports them.
    """

    id: str
    symbol: str
    side: str  # "buy", "sell" or "" for adjustments
    volume: float
    open_time: datetime | None
    close_time: datetime
    pnl: float
    open_price: float | None = None
    close_price: float | None = None
    commission: float = 0.0
    swap: float = 0.0
    mae: float | None = None  # worst floating P/L seen during the trade (<= 0), if known
    kind: str = "trade"  # "trade" or "adjustment"

    @property
    def is_trade(self) -> bool:
        return self.kind == "trade"


@dataclass
class TradeHistory:
    """The result of :func:`prop_rules_checker.load_trades`."""

    trades: list[Trade]
    format: str
    source: str = "<memory>"
    notes: list[str] = field(default_factory=list)
    volume_unit: str = "lots"

    def __iter__(self) -> Iterator[Trade]:
        return iter(self.trades)

    def __len__(self) -> int:
        return len(self.trades)


@dataclass(frozen=True)
class NewsEvent:
    time: datetime
    title: str = ""
    currency: str = ""
    impact: str = ""
    symbols: tuple[str, ...] = ()
