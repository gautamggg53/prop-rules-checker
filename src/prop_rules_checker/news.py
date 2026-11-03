"""User-supplied news/economic events (CSV).

Columns (case-insensitive): ``time`` (required), ``currency``, ``impact``,
``title`` (or ``event``), ``symbols`` (``;`` or ``|`` separated). An event with
``symbols`` applies to those symbols; otherwise one with ``currency`` applies to
symbols containing that currency code (``USD`` matches ``EURUSD`` and ``XAUUSD``);
an event with neither applies to every symbol.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import InputError, NewsEvent
from .parsers.common import get_tz, norm, parse_datetime, read_csv_rows, read_text


def load_news(
    path: str | Path, *, tz: str = "UTC", date_format: str | None = None
) -> list[NewsEvent]:
    rows, _ = read_csv_rows(read_text(path))
    header = [norm(h) for h in rows[0]]

    def col(*names: str) -> int | None:
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_time = col("time", "datetime", "date/time", "timestamp")
    if i_time is None:
        raise InputError(f"{path}: news file needs a 'time' column")
    i_cur, i_imp = col("currency", "country"), col("impact", "importance")
    i_title, i_sym = col("title", "event", "name"), col("symbols", "symbol")
    zone = get_tz(tz)
    events: list[NewsEvent] = []
    for n, row in enumerate(rows[1:], start=2):

        def get(i: int | None, row: list[str] = row) -> str:
            return row[i].strip() if i is not None and i < len(row) else ""

        syms = tuple(s.strip().upper() for s in re.split(r"[;|]", get(i_sym)) if s.strip())
        events.append(
            NewsEvent(
                time=parse_datetime(get(i_time), zone, fmt=date_format, field=f"time on row {n}"),
                title=get(i_title),
                currency=get(i_cur).upper(),
                impact=get(i_imp).lower(),
                symbols=syms,
            )
        )
    return sorted(events, key=lambda e: e.time)


def _clean(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", symbol.upper())


def event_applies(event: NewsEvent, symbol: str) -> bool:
    sym = _clean(symbol)
    if event.symbols:
        return any(_clean(s) and sym.startswith(_clean(s)) for s in event.symbols)
    if event.currency:
        return event.currency in sym
    return True
