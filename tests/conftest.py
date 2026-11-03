from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from prop_rules_checker import Trade, rules_from_dict

FIXTURES = Path(__file__).parent / "fixtures"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def trade(
    tid: str,
    close: str,
    pnl: float,
    *,
    open_: str | None = None,
    symbol: str = "EURUSD",
    volume: float = 1.0,
    mae: float | None = None,
    kind: str = "trade",
) -> Trade:
    return Trade(
        id=tid,
        symbol=symbol,
        side="buy",
        volume=volume,
        open_time=utc(open_) if open_ else None,
        close_time=utc(close),
        pnl=pnl,
        mae=mae,
        kind=kind,
    )


def ruleset(
    rules: dict[str, Any],
    *,
    balance: float = 100_000,
    tz: str = "UTC",
    reset: str = "00:00",
    warn_at: float | None = None,
):
    data: dict[str, Any] = {
        "name": "test",
        "account": {"initial_balance": balance, "currency": "USD"},
        "day_reset": {"timezone": tz, "time": reset},
        "rules": rules,
    }
    if warn_at is not None:
        data["warn_at"] = warn_at
    return rules_from_dict(data)


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
