from __future__ import annotations

from datetime import date

import pytest

from conftest import ruleset, trade, utc
from prop_rules_checker import NewsEvent, Status, TradeHistory, check
from prop_rules_checker.report import render_text

DAILY = {"daily_loss": {"limit_pct": 5}}


# ---------------------------------------------------------------- daily loss


def test_daily_loss_pass_warn_fail():
    rules = ruleset(DAILY)
    ok = check([trade("a", "2026-03-02T10:00", -3000)], rules)
    assert ok.result("daily_loss").status is Status.PASS
    warn = check([trade("a", "2026-03-02T10:00", -4000)], rules)
    assert warn.result("daily_loss").status is Status.WARN
    fail = check(
        [trade("a", "2026-03-02T10:00", -3000), trade("b", "2026-03-02T11:00", -2500)], rules
    )
    res = fail.result("daily_loss")
    assert res.status is Status.FAIL and fail.has_violations
    assert res.findings[0].trade_ids == ("b",)
    assert "trade b" in res.findings[0].message and "over by" in res.findings[0].message


def test_daily_loss_exact_limit_is_warning_not_violation():
    report = check([trade("a", "2026-03-02T10:00", -5000)], ruleset(DAILY))
    assert report.result("daily_loss").status is Status.WARN
    assert not report.has_violations


def test_daily_loss_intraday_low_counts_even_if_day_recovers():
    trades = [trade("a", "2026-03-02T09:00", -5200), trade("b", "2026-03-02T12:00", 6000)]
    assert check(trades, ruleset(DAILY)).result("daily_loss").status is Status.FAIL


def test_daily_loss_profit_earlier_in_day_is_measured_from_day_start():
    # +3000 then -7000: the day's low is 4000 below the day's start (not 7000).
    trades = [trade("a", "2026-03-02T09:00", 3000), trade("b", "2026-03-02T12:00", -7000)]
    res = check(trades, ruleset(DAILY, warn_at=0.9)).result("daily_loss")
    assert res.status is Status.PASS
    assert res.metrics["days"][0]["loss"] == pytest.approx(4000)


def test_daily_loss_resets_at_configured_hour_and_timezone():
    # 22:30 and 23:30 UTC on 2 March are on different Prague days (UTC+1 in March).
    trades = [trade("a", "2026-03-02T22:30", -3000), trade("b", "2026-03-02T23:30", -3000)]
    utc_rules = ruleset(DAILY)
    assert check(trades, utc_rules).result("daily_loss").status is Status.FAIL
    prague = ruleset(DAILY, tz="Europe/Prague")
    res = check(trades, prague).result("daily_loss")
    assert res.status is Status.PASS
    assert [d["day"] for d in res.metrics["days"]] == [date(2026, 3, 2), date(2026, 3, 3)]


def test_day_reset_at_17_new_york_labels_by_end_date_and_handles_dst():
    rules = ruleset(DAILY, tz="America/New_York", reset="17:00")
    # 20:30 UTC on Fri 6 Mar = 15:30 EST -> session ending Fri 6 Mar.
    # 21:30 UTC on Mon 9 Mar = 17:30 EDT (DST started 8 Mar) -> session ending Tue 10 Mar.
    trades = [
        trade("a", "2026-03-06T20:30", -100),
        trade("b", "2026-03-09T21:30", -100),
        trade("c", "2026-03-09T20:30", -100),
    ]
    days = [d["day"] for d in check(trades, rules).result("daily_loss").metrics["days"]]
    assert days == [date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10)]


def test_daily_loss_reference_day_start_balance():
    rules = ruleset({"daily_loss": {"limit_pct": 5, "reference": "day_start_balance"}})
    trades = [trade("a", "2026-03-02T10:00", 20000), trade("b", "2026-03-03T10:00", -5500)]
    res = check(trades, rules).result("daily_loss")
    assert res.metrics["days"][1]["limit"] == pytest.approx(6000)
    assert res.status is Status.WARN


def test_daily_loss_amount_and_equity_with_mae():
    rules = ruleset({"daily_loss": {"limit_amount": 1000, "measure": "equity"}})
    # Closed loss is only 200 but the trade was 1200 under water at worst.
    trades = [trade("a", "2026-03-02T10:00", -200, open_="2026-03-02T09:00", mae=-1200)]
    report = check(trades, rules)
    res = report.result("daily_loss")
    assert res.status is Status.FAIL and res.approximated
    assert any("Equity-based limits are estimated" in a for a in report.assumptions)
    no_mae = check([trade("a", "2026-03-02T10:00", -200)], rules)
    assert no_mae.result("daily_loss").status is Status.PASS
    assert any("would NOT show" in a for a in no_mae.assumptions)
    assert "closed balance only" in no_mae.result("daily_loss").summary
    text = render_text(no_mae)
    assert text.index("Closed-trade limits") < text.index("RULE")
    assert "would NOT show" in text.split("RULE")[0]
    assert "would NOT show" not in text.split("Assumptions and limitations:")[1]


def test_equity_estimate_sums_overlapping_trades():
    rules = ruleset({"max_drawdown": {"limit_amount": 1000, "measure": "equity"}})
    trades = [
        trade("a", "2026-03-02T12:00", 0, open_="2026-03-02T09:00", mae=-600),
        trade("b", "2026-03-02T11:00", 0, open_="2026-03-02T10:00", mae=-500),
        trade("c", "2026-03-02T15:00", 0, open_="2026-03-02T14:00", mae=-100),
    ]
    res = check(trades, rules).result("max_drawdown")
    assert res.metrics["lowest"] == pytest.approx(100_000 - 1100)
    assert res.status is Status.FAIL


def test_equity_estimate_without_open_time_uses_own_mae():
    rules = ruleset({"max_drawdown": {"limit_amount": 1000, "measure": "equity"}})
    res = check([trade("a", "2026-03-02T12:00", 0, mae=-900)], rules).result("max_drawdown")
    assert res.metrics["lowest"] == pytest.approx(99_100)
    assert res.status is Status.WARN


# ---------------------------------------------------------------- drawdowns


def test_static_max_drawdown():
    rules = ruleset({"max_drawdown": {"limit_pct": 10}})
    trades = [trade(str(i), f"2026-03-0{i + 2}T10:00", -2500) for i in range(4)]
    at_floor = check(trades, rules)  # exactly at the floor: warning, not a violation
    assert at_floor.result("max_drawdown").status is Status.WARN and not at_floor.has_violations
    trades.append(trade("x", "2026-03-07T10:00", -1))
    res = check(trades, rules).result("max_drawdown")
    assert res.status is Status.FAIL and res.findings[0].trade_ids == ("x",)
    assert check(trades[:3], rules).result("max_drawdown").status is Status.PASS
    warn = check(trades[:4], ruleset({"max_drawdown": {"limit_pct": 11}}))
    assert warn.result("max_drawdown").status is Status.WARN


def test_static_drawdown_does_not_trail():
    rules = ruleset({"max_drawdown": {"limit_amount": 5000}})
    trades = [trade("a", "2026-03-02T10:00", 10000), trade("b", "2026-03-03T10:00", -9000)]
    assert check(trades, rules).result("max_drawdown").status is Status.PASS


def test_trailing_drawdown_follows_closed_balance_high():
    rules = ruleset({"trailing_drawdown": {"limit_amount": 5000}})
    trades = [trade("a", "2026-03-02T10:00", 10000), trade("b", "2026-03-03T10:00", -5001)]
    res = check(trades, rules).result("trailing_drawdown")
    assert res.status is Status.FAIL
    assert res.findings[0].limit == pytest.approx(105_000)


def test_trailing_drawdown_locks_at_initial_balance():
    lock = ruleset({"trailing_drawdown": {"limit_amount": 5000, "lock_at": "initial_balance"}})
    trades = [trade("a", "2026-03-02T10:00", 8000), trade("b", "2026-03-03T10:00", -7900)]
    res = check(trades, lock).result("trailing_drawdown")
    assert res.status is Status.WARN  # floor locked at 100k; balance 100,100
    assert res.metrics["floor"] == 100_000 and res.metrics["locked_at"] is not None
    no_lock = ruleset({"trailing_drawdown": {"limit_amount": 5000}})
    assert check(trades, no_lock).result("trailing_drawdown").status is Status.FAIL


def test_trailing_lock_not_reached_keeps_trailing():
    lock = ruleset({"trailing_drawdown": {"limit_amount": 5000, "lock_at": "initial_balance"}})
    trades = [trade("a", "2026-03-02T10:00", 3000), trade("b", "2026-03-03T10:00", -8001)]
    res = check(trades, lock).result("trailing_drawdown")
    assert res.status is Status.FAIL and res.metrics["locked_at"] is None
    assert res.findings[0].limit == pytest.approx(98_000)


def test_trailing_lock_at_custom_level():
    rules = ruleset({"trailing_drawdown": {"limit_pct": 5, "lock_at": 100_500}})
    trades = [trade("a", "2026-03-02T10:00", 9000), trade("b", "2026-03-03T10:00", -8400)]
    res = check(trades, rules).result("trailing_drawdown")
    assert res.metrics["floor"] == 100_500 and res.status is Status.WARN


# ---------------------------------------------------------------- objectives


def test_profit_target_states():
    rules = ruleset({"profit_target": {"target_pct": 8}})
    hit = check([trade("a", "2026-03-02T10:00", 8000)], rules).result("profit_target")
    assert hit.status is Status.PASS
    short = check([trade("a", "2026-03-02T10:00", 2000)], rules).result("profit_target")
    assert short.status is Status.PENDING and short.metrics["progress"] == pytest.approx(0.25)
    gave_back = check(
        [trade("a", "2026-03-02T10:00", 9000), trade("b", "2026-03-03T10:00", -2000)], rules
    )
    res = gave_back.result("profit_target")
    assert res.status is Status.PENDING and "since dropped" in res.summary
    amt = ruleset({"profit_target": {"target_amount": 500}})
    assert (
        check([trade("a", "2026-03-02T10:00", 500)], amt).result("profit_target").status
        is Status.PASS
    )


def test_min_trading_days_counting_modes():
    t = [
        trade("a", "2026-03-03T10:00", 1, open_="2026-03-02T10:00"),
        trade("b", "2026-03-03T12:00", 1, open_="2026-03-03T11:00"),
        trade("c", "2026-03-04T10:00", 1),  # no open time -> close day
        trade("fee", "2026-03-05T10:00", -1, kind="adjustment"),
    ]
    for mode, expected in (("open", 3), ("close", 2), ("any", 3)):
        res = check(t, ruleset({"min_trading_days": {"days": 3, "count_by": mode}}))
        assert res.result("min_trading_days").metrics["count"] == expected
    res = check(t, ruleset({"min_trading_days": {"days": 4}})).result("min_trading_days")
    assert res.status is Status.PENDING and "minimum 4" in res.summary


# ---------------------------------------------------------------- consistency


def test_consistency_basic_and_needed_profit():
    rules = ruleset({"consistency": {"max_best_day_pct": 40}})
    trades = [
        trade("a", "2026-03-02T10:00", 3000),
        trade("b", "2026-03-03T10:00", 1000),
        trade("c", "2026-03-04T10:00", 1000),
    ]
    res = check(trades, rules).result("consistency")
    assert res.status is Status.FAIL
    assert res.metrics["ratio"] == pytest.approx(0.6)
    assert res.metrics["additional_profit_needed"] == pytest.approx(2500)


def test_consistency_with_losing_days_depends_on_denominator():
    trades = [
        trade("a", "2026-03-02T10:00", 2000),
        trade("b", "2026-03-03T10:00", 2000),
        trade("c", "2026-03-04T10:00", 2000),
        trade("d", "2026-03-05T10:00", -2000),
    ]
    net = check(trades, ruleset({"consistency": {"max_best_day_pct": 40}}))
    assert net.result("consistency").status is Status.FAIL  # 2000 / 4000 = 50%
    pos = check(
        trades, ruleset({"consistency": {"max_best_day_pct": 40, "denominator": "positive_days"}})
    )
    assert pos.result("consistency").status is Status.WARN  # 2000 / 6000 = 33%


def test_consistency_not_applicable_without_profit():
    rules = ruleset({"consistency": {"max_best_day_pct": 40}})
    res = check([trade("a", "2026-03-02T10:00", -100)], rules).result("consistency")
    assert res.status is Status.INFO
    res = check(
        [trade("a", "2026-03-02T10:00", 100), trade("b", "2026-03-03T10:00", -300)], rules
    ).result("consistency")
    assert res.status is Status.INFO


def test_consistency_groups_trades_by_trading_day():
    rules = ruleset({"consistency": {"max_best_day_pct": 50}}, tz="Europe/Prague")
    trades = [
        trade("a", "2026-03-02T22:00", 500),
        trade("b", "2026-03-02T23:30", 500),
        trade("c", "2026-03-04T10:00", 1000),
    ]
    assert check(trades, rules).result("consistency").status is Status.WARN  # 50% exactly


# ---------------------------------------------------------------- news

NEWS = [
    NewsEvent(utc("2026-03-05T13:30"), "CPI", "USD", "high"),
    NewsEvent(utc("2026-03-05T09:00"), "PMI", "EUR", "low"),
    NewsEvent(utc("2026-03-05T15:00"), "Oil inventories", "", "high", ("USOIL", "UKOIL")),
]
NEWS_RULE = {"news_trading": {"minutes_before": 2, "minutes_after": 2, "impacts": ["high"]}}


def test_news_open_and_close_inside_window():
    trades = [
        trade("o", "2026-03-05T14:00", 10, open_="2026-03-05T13:28"),
        trade("c", "2026-03-05T13:32", 10, open_="2026-03-05T12:00"),
        trade("x", "2026-03-05T13:27", 10, open_="2026-03-05T12:00"),
    ]
    res = check(trades, ruleset(NEWS_RULE), news=NEWS).result("news_trading")
    fails = {f.trade_ids[0] for f in res.findings if f.status is Status.FAIL}
    assert fails == {"o", "c"} and res.status is Status.FAIL


def test_news_currency_symbol_and_impact_matching():
    trades = [
        trade("jpy", "2026-03-05T13:31", 1, open_="2026-03-05T13:29", symbol="EURJPY"),
        trade("low", "2026-03-05T09:01", 1, open_="2026-03-05T08:00"),
        trade("oil", "2026-03-05T15:01", 1, open_="2026-03-05T14:00", symbol="USOIL.cash"),
        trade("gold", "2026-03-05T13:31", 1, open_="2026-03-05T13:00", symbol="XAUUSD"),
    ]
    res = check(trades, ruleset(NEWS_RULE), news=NEWS).result("news_trading")
    assert {f.trade_ids[0] for f in res.findings} == {"oil", "gold"}
    every = check(trades[1:2], ruleset({"news_trading": {"impacts": []}}), news=NEWS)
    assert every.result("news_trading").status is Status.FAIL  # low impact included


def test_news_hold_through_and_buffer():
    held = [trade("h", "2026-03-05T14:00", 1, open_="2026-03-05T13:00")]
    warn = check(held, ruleset(NEWS_RULE), news=NEWS).result("news_trading")
    assert warn.status is Status.WARN
    forbid = ruleset({"news_trading": {"hold_through": "forbid", "impacts": ["high"]}})
    assert check(held, forbid, news=NEWS).result("news_trading").status is Status.FAIL
    allow = ruleset({"news_trading": {"hold_through": "allow"}})
    assert check(held, allow, news=NEWS).result("news_trading").status is Status.PASS
    near = [trade("n", "2026-03-05T13:26", 1, open_="2026-03-05T12:00")]
    buf = ruleset({"news_trading": {"warn_buffer_minutes": 5, "impacts": ["high"]}})
    assert check(near, buf, news=NEWS).result("news_trading").status is Status.WARN


def test_news_close_only_and_skipped_without_file():
    rules = ruleset({"news_trading": {"check": ["close"], "hold_through": "allow"}})
    t = [trade("o", "2026-03-05T14:00", 10, open_="2026-03-05T13:30")]
    assert check(t, rules, news=NEWS).result("news_trading").status is Status.PASS
    assert check(t, rules).result("news_trading").status is Status.SKIPPED


# ---------------------------------------------------------------- weekend

WEEKEND = {
    "weekend_holding": {
        "allowed": False,
        "timezone": "America/New_York",
        "friday_close": "17:00",
        "sunday_open": "17:00",
        "warn_within_minutes": 15,
        "exempt_symbols": ["BTCUSD"],
    }
}


def test_weekend_holding_detection_in_timezone():
    rules = ruleset(WEEKEND)
    # Fri 6 Mar 2026 17:00 EST = 22:00 UTC.
    held = trade("held", "2026-03-09T14:00", 1, open_="2026-03-06T21:00")
    before = trade("ok", "2026-03-06T21:59", 1, open_="2026-03-06T20:00")
    close_call = trade("near", "2026-03-06T21:50", 1, open_="2026-03-06T20:00")
    early = trade("early", "2026-03-06T20:00", 1, open_="2026-03-06T19:00")
    crypto = trade("btc", "2026-03-09T14:00", 1, open_="2026-03-06T21:00", symbol="BTCUSD")
    res = check([held, before, close_call, early, crypto], rules).result("weekend_holding")
    statuses = {f.trade_ids[0]: f.status for f in res.findings}
    assert statuses == {"held": Status.FAIL, "ok": Status.WARN, "near": Status.WARN}
    assert res.status is Status.FAIL


def test_weekend_opened_during_weekend_and_multi_week():
    rules = ruleset(WEEKEND)
    sat = trade("sat", "2026-03-08T23:00", 1, open_="2026-03-07T12:00")
    long_ = trade("long", "2026-03-20T15:00", 1, open_="2026-03-10T15:00")
    res = check([sat, long_], rules).result("weekend_holding")
    assert {f.trade_ids[0] for f in res.findings if f.status is Status.FAIL} == {"sat", "long"}


def test_weekend_allowed_and_unknown_open_times():
    allowed = ruleset({"weekend_holding": {"allowed": True}})
    held = trade("held", "2026-03-09T14:00", 1, open_="2026-03-06T21:00")
    res = check([held], allowed).result("weekend_holding")
    assert res.status is Status.INFO and not check([held], allowed).has_violations
    quiet = check([trade("a", "2026-03-04T10:00", 1, open_="2026-03-04T09:00")], allowed)
    assert quiet.result("weekend_holding").status is Status.PASS
    no_open = check([trade("x", "2026-03-04T10:00", 1)], ruleset(WEEKEND))
    assert no_open.result("weekend_holding").status is Status.SKIPPED


# ---------------------------------------------------------------- lots


def test_lot_size_per_trade_and_open_lots():
    rules = ruleset({"lot_size": {"max_lots_per_trade": 5, "max_open_lots": 8}})
    trades = [
        trade("a", "2026-03-02T12:00", 1, open_="2026-03-02T10:00", volume=4),
        trade("b", "2026-03-02T13:00", 1, open_="2026-03-02T11:00", volume=5),
        trade("c", "2026-03-02T14:00", 1, open_="2026-03-02T13:00", volume=3),
    ]
    res = check(trades, rules).result("lot_size")
    assert res.metrics["peak_open"] == 9 and res.status is Status.FAIL
    peak = next(f for f in res.findings if "at once" in f.message)
    assert set(peak.trade_ids) == {"a", "b"}
    assert {f.trade_ids[0] for f in res.findings if "vs max" in f.message} == {"a", "b"}


def test_open_lots_close_and_open_at_same_instant_do_not_overlap():
    rules = ruleset({"lot_size": {"max_open_lots": 5}})
    trades = [
        trade("a", "2026-03-02T12:00", 1, open_="2026-03-02T10:00", volume=5),
        trade("b", "2026-03-02T13:00", 1, open_="2026-03-02T12:00", volume=5),
    ]
    res = check(trades, rules).result("lot_size")
    assert res.metrics["peak_open"] == 5 and res.status is Status.WARN


def test_lot_units_note_and_adjustments_ignored():
    rules = ruleset({"lot_size": {"max_lots_per_trade": 10}})
    h = TradeHistory(
        [
            trade("a", "2026-03-02T12:00", 1, volume=2),
            trade("fee", "2026-03-02T12:00", -1, volume=99, kind="adjustment"),
        ],
        format="x",
        volume_unit="units",
    )
    res = check(h, rules).result("lot_size")
    assert res.status is Status.PASS and "units" in res.summary


# ---------------------------------------------------------------- report / api


def test_check_arguments_and_report_json():
    rules = ruleset({**DAILY, "profit_target": {"target_pct": 1}}, warn_at=0.5)
    trades = [trade("a", "2026-03-02T10:00", -3000), trade("b", "2026-03-03T10:00", 4500)]
    report = check(trades, rules)
    assert report.warn_at == 0.5 and report.result("daily_loss").status is Status.WARN
    assert check(trades, rules, warn_at=0.9).result("daily_loss").status is Status.PASS
    data = report.to_dict()
    assert data["status"] == "warn" and data["net_pnl"] == 1500
    assert data["results"][0]["metrics"]["days"][0]["day"] == "2026-03-02"
    assert '"rule": "daily_loss"' in report.to_json()
    with pytest.raises(KeyError):
        report.result("nope")
    with pytest.raises(ValueError):
        check([], rules)
    with pytest.raises(ValueError):
        check(trades, rules, warn_at=1.5)
