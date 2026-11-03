"""Loading and validating rule sets (YAML or JSON)."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import time
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .models import InputError
from .parsers.common import get_tz
from .schema import validate

DEFAULTS: dict[str, dict[str, Any]] = {
    "daily_loss": {"reference": "initial_balance", "measure": "balance"},
    "max_drawdown": {"measure": "balance"},
    "trailing_drawdown": {"measure": "balance", "lock_at": None},
    "profit_target": {},
    "consistency": {"denominator": "net_profit"},
    "min_trading_days": {"count_by": "open"},
    "news_trading": {
        "minutes_before": 2,
        "minutes_after": 2,
        "impacts": [],
        "check": ["open", "close"],
        "hold_through": "warn",
        "warn_buffer_minutes": 0,
    },
    "weekend_holding": {
        "allowed": False,
        "timezone": None,
        "friday_close": "22:00",
        "sunday_open": "22:00",
        "warn_within_minutes": 0,
        "exempt_symbols": [],
    },
    "lot_size": {},
}
RULE_ORDER = list(DEFAULTS)


@dataclass
class RuleSet:
    name: str
    initial_balance: float
    currency: str = ""
    description: str = ""
    day_reset_timezone: str = "UTC"
    day_reset_time: time = field(default_factory=lambda: time(0, 0))
    warn_at: float | None = None
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    source: str = "<memory>"


def _parse_hhmm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def list_presets() -> list[str]:
    """Names of the bundled example presets."""
    folder = resources.files("prop_rules_checker") / "presets"
    return sorted(
        p.name.rsplit(".", 1)[0]
        for p in folder.iterdir()
        if p.name.endswith((".yaml", ".yml", ".json"))
    )


def _read_rules_text(path_or_name: str | Path) -> tuple[str, str]:
    p = Path(path_or_name)
    if p.is_file():
        return p.read_text(encoding="utf-8"), str(p)
    name = p.name.rsplit(".", 1)[0] if p.suffix in (".yaml", ".yml", ".json") else p.name
    folder = resources.files("prop_rules_checker") / "presets"
    for ext in (".yaml", ".yml", ".json"):
        candidate = folder / f"{name}{ext}"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8"), f"preset:{name}"
    raise InputError(
        f"rules file not found: {path_or_name} (bundled presets: {', '.join(list_presets())})"
    )


def rules_from_dict(data: Any, source: str = "<memory>") -> RuleSet:
    """Validate a parsed rule-set mapping and return a :class:`RuleSet`."""
    errors = validate(data)
    if isinstance(data, dict) and isinstance(data.get("rules"), dict):
        for key, cfg in data["rules"].items():
            if not isinstance(cfg, dict):
                continue
            if key in ("daily_loss", "max_drawdown", "trailing_drawdown"):
                n = sum(k in cfg for k in ("limit_pct", "limit_amount"))
                if n != 1:
                    errors.append(f"$.rules.{key}: set exactly one of limit_pct or limit_amount")
            if (
                key == "profit_target"
                and sum(k in cfg for k in ("target_pct", "target_amount")) != 1
            ):
                errors.append(
                    "$.rules.profit_target: set exactly one of target_pct or target_amount"
                )
            if key == "lot_size" and not cfg:
                errors.append("$.rules.lot_size: set max_lots_per_trade and/or max_open_lots")
        if not data["rules"]:
            errors.append("$.rules: enable at least one rule")
    if errors:
        raise InputError(f"invalid rule set {source}:\n  - " + "\n  - ".join(errors))
    reset = data.get("day_reset", {})
    tz_name = reset.get("timezone", "UTC")
    get_tz(tz_name)
    rules: dict[str, dict[str, Any]] = {}
    for key in RULE_ORDER:
        if key in data["rules"]:
            cfg = copy.deepcopy(DEFAULTS[key])
            cfg.update(data["rules"][key])
            rules[key] = cfg
    if "weekend_holding" in rules:
        rules["weekend_holding"]["timezone"] = rules["weekend_holding"]["timezone"] or tz_name
        get_tz(rules["weekend_holding"]["timezone"])
    return RuleSet(
        name=data["name"],
        description=data.get("description", ""),
        initial_balance=float(data["account"]["initial_balance"]),
        currency=data["account"].get("currency", ""),
        day_reset_timezone=tz_name,
        day_reset_time=_parse_hhmm(reset.get("time", "00:00")),
        warn_at=data.get("warn_at"),
        rules=rules,
        source=source,
    )


def load_rules(path_or_name: str | Path) -> RuleSet:
    """Load a YAML or JSON rule set from a path, or a bundled preset by name."""
    text, source = _read_rules_text(path_or_name)
    try:
        if source.endswith(".json") or text.lstrip().startswith("{"):
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise InputError(f"cannot parse rules file {source}: {exc}") from exc
    return rules_from_dict(data, source)
