from __future__ import annotations

import json
from pathlib import Path

import pytest

from prop_rules_checker import InputError, list_presets, load_news, load_rules, rules_from_dict
from prop_rules_checker.news import event_applies
from prop_rules_checker.schema import RULES_SCHEMA, validate

ROOT = Path(__file__).resolve().parents[1]
BASE = {
    "name": "t",
    "account": {"initial_balance": 1000},
    "rules": {"daily_loss": {"limit_pct": 5}},
}


def test_bundled_presets_are_valid_and_labelled():
    names = list_presets()
    assert {"example-2step-challenge", "example-1step-trailing", "example-funded-account"} <= set(
        names
    )
    for name in names:
        rs = load_rules(name)
        assert "illustrative" in rs.name.lower()
        assert rs.source == f"preset:{name}"
    for path in (ROOT / "src/prop_rules_checker/presets").iterdir():
        assert "ILLUSTRATIVE EXAMPLE ONLY" in path.read_text()


def test_load_by_path_and_extension(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "name: mine\naccount: {initial_balance: 5000}\nrules:\n  max_drawdown:\n"
        "    limit_amount: 500\n"
    )
    assert load_rules(p).rules["max_drawdown"]["measure"] == "balance"
    j = tmp_path / "r.json"
    j.write_text(json.dumps(BASE))
    assert load_rules(j).initial_balance == 1000
    assert load_rules("example-1step-trailing.yaml").name.startswith("Example 1-step")


def test_published_schema_matches_code():
    published = json.loads((ROOT / "schema/rules.schema.json").read_text())
    assert published == json.loads(json.dumps(RULES_SCHEMA))


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"rules": {}}, "at least one rule"),
        ({"rules": {"daily_loss": {}}}, "exactly one of limit_pct"),
        ({"rules": {"daily_loss": {"limit_pct": 5, "limit_amount": 1}}}, "exactly one"),
        ({"rules": {"daily_loss": {"limit_pct": 150}}}, "<= 100"),
        ({"rules": {"daily_loss": {"limit_pct": 0}}}, "> 0"),
        ({"rules": {"daily_loss": {"limit_pct": "5"}}}, "expected number"),
        ({"rules": {"daily_loss": {"limit_pct": 5, "measure": "vibes"}}}, "must be one of"),
        ({"rules": {"dailyloss": {"limit_pct": 5}}}, "unknown key"),
        ({"rules": {"profit_target": {}}}, "target_pct or target_amount"),
        ({"rules": {"lot_size": {}}}, "max_lots_per_trade"),
        ({"rules": {"consistency": {}}}, "missing required key 'max_best_day_pct'"),
        ({"rules": {"min_trading_days": {"days": 2.5}}}, "expected integer"),
        ({"rules": {"min_trading_days": {"days": True}}}, "expected integer"),
        ({"rules": {"news_trading": {"check": []}}}, "at least 1"),
        ({"rules": {"news_trading": {"check": ["middle"]}}}, "must be one of"),
        ({"rules": {"trailing_drawdown": {"limit_pct": 5, "lock_at": "peak"}}}, "not allowed"),
        ({"rules": {"weekend_holding": {"friday_close": "25:00"}}}, "HH:MM"),
        ({"rules": {"daily_loss": {"limit_pct": 5, "minimum": -1}}}, "unknown key"),
        ({"day_reset": {"timezone": "Nowhere/Land"}}, "unknown timezone"),
        ({"warn_at": 2}, "<= 1"),
        ({"name": ""}, "must not be empty"),
        ({"account": {}}, "initial_balance"),
    ],
)
def test_validation_errors(patch, message):
    data = {**BASE, **patch}
    with pytest.raises(InputError, match=message):
        rules_from_dict(data)


def test_validation_of_non_mapping_and_bad_files(tmp_path):
    with pytest.raises(InputError, match="expected object"):
        rules_from_dict(["not", "a", "mapping"])
    p = tmp_path / "bad.yaml"
    p.write_text("name: [unclosed\n")
    with pytest.raises(InputError, match="cannot parse"):
        load_rules(p)
    with pytest.raises(InputError, match="bundled presets"):
        load_rules(tmp_path / "missing.yaml")
    assert validate(5, {"minimum": 10}) == ["$: must be >= 10"]


def test_weekend_timezone_defaults_to_day_reset_zone():
    data = {**BASE, "day_reset": {"timezone": "Asia/Tokyo"}, "rules": {"weekend_holding": {}}}
    assert rules_from_dict(data).rules["weekend_holding"]["timezone"] == "Asia/Tokyo"
    data["rules"] = {"weekend_holding": {"timezone": "Bad/Zone"}}
    with pytest.raises(InputError):
        rules_from_dict(data)


def test_load_news(tmp_path, fixtures):
    events = load_news(fixtures / "synthetic_news_events.csv")
    assert events[0].title == "EU sentiment (synthetic)"  # sorted by time
    assert events[1].currency == "USD" and events[1].impact == "high"
    p = tmp_path / "n.csv"
    p.write_text("Timestamp,Event,Symbols\n2026-03-05 08:30,Something,US30|NAS100\n")
    ev = load_news(p, tz="America/New_York")[0]
    assert ev.time.hour == 13 and ev.symbols == ("US30", "NAS100")
    assert event_applies(ev, "nas100.cash") and not event_applies(ev, "EURUSD")
    p.write_text("when,what\nx,y\n")
    with pytest.raises(InputError, match="time"):
        load_news(p)
