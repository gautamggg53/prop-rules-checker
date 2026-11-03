"""JSON Schema for rule sets, plus a small dependency-free validator.

The same schema is published as ``schema/rules.schema.json`` (draft 2020-12) for
editor integration. The validator implements the subset used here: type,
properties, required, additionalProperties, enum, minimum, maximum,
exclusiveMinimum, pattern, items, minItems, anyOf.
"""

from __future__ import annotations

import re
from typing import Any

_LIMIT = {
    "limit_pct": {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": 100,
        "description": "Limit as a percentage (of the reference balance).",
    },
    "limit_amount": {
        "type": "number",
        "exclusiveMinimum": 0,
        "description": "Limit as an amount in account currency.",
    },
}
_MEASURE = {
    "type": "string",
    "enum": ["balance", "equity"],
    "description": "equity is approximated from closed trades (see README).",
}
_HHMM = {"type": "string", "pattern": r"^([01]\d|2[0-3]):[0-5]\d$"}

RULES_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "prop-rules-checker rule set",
    "type": "object",
    "required": ["name", "account", "rules"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "account": {
            "type": "object",
            "required": ["initial_balance"],
            "additionalProperties": False,
            "properties": {
                "initial_balance": {"type": "number", "exclusiveMinimum": 0},
                "currency": {"type": "string"},
            },
        },
        "day_reset": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "timezone": {"type": "string", "description": "IANA zone, e.g. Europe/Prague"},
                "time": _HHMM,
            },
        },
        "warn_at": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "rules": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "daily_loss": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        **_LIMIT,
                        "reference": {
                            "type": "string",
                            "enum": ["initial_balance", "day_start_balance"],
                        },
                        "measure": _MEASURE,
                    },
                },
                "max_drawdown": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {**_LIMIT, "measure": _MEASURE},
                },
                "trailing_drawdown": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        **_LIMIT,
                        "measure": _MEASURE,
                        "lock_at": {
                            "anyOf": [
                                {"type": "string", "enum": ["initial_balance"]},
                                {"type": "number", "exclusiveMinimum": 0},
                                {"type": "null"},
                            ]
                        },
                    },
                },
                "profit_target": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "target_pct": {"type": "number", "exclusiveMinimum": 0},
                        "target_amount": {"type": "number", "exclusiveMinimum": 0},
                    },
                },
                "consistency": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["max_best_day_pct"],
                    "properties": {
                        "max_best_day_pct": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "maximum": 100,
                        },
                        "denominator": {"type": "string", "enum": ["net_profit", "positive_days"]},
                    },
                },
                "min_trading_days": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["days"],
                    "properties": {
                        "days": {"type": "integer", "minimum": 1},
                        "count_by": {"type": "string", "enum": ["open", "close", "any"]},
                    },
                },
                "news_trading": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "minutes_before": {"type": "number", "minimum": 0},
                        "minutes_after": {"type": "number", "minimum": 0},
                        "impacts": {"type": "array", "items": {"type": "string"}},
                        "check": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "enum": ["open", "close"]},
                        },
                        "hold_through": {"type": "string", "enum": ["forbid", "warn", "allow"]},
                        "warn_buffer_minutes": {"type": "number", "minimum": 0},
                    },
                },
                "weekend_holding": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "allowed": {"type": "boolean"},
                        "timezone": {"type": "string"},
                        "friday_close": _HHMM,
                        "sunday_open": _HHMM,
                        "warn_within_minutes": {"type": "number", "minimum": 0},
                        "exempt_symbols": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "lot_size": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "max_lots_per_trade": {"type": "number", "exclusiveMinimum": 0},
                        "max_open_lots": {"type": "number", "exclusiveMinimum": 0},
                    },
                },
            },
        },
    },
}

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[expected])


def validate(instance: Any, schema: dict[str, Any] = RULES_SCHEMA, path: str = "$") -> list[str]:
    """Return a list of human-readable errors (empty when valid)."""
    errors: list[str] = []
    if "anyOf" in schema:
        if not any(not validate(instance, s, path) for s in schema["anyOf"]):
            errors.append(f"{path}: value {instance!r} is not allowed")
        return errors
    expected = schema.get("type")
    if expected and not _type_ok(instance, expected):
        return [f"{path}: expected {expected}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}, got {instance!r}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: must be > {schema['exclusiveMinimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}")
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(
                f"{path}: {instance!r} has the wrong format (expected HH:MM)"
                if schema is _HHMM
                else f"{path}: {instance!r} has the wrong format"
            )
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{path}: must not be empty")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for i, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required key '{key}'")
        for key, value in instance.items():
            sub = f"{path}.{key}"
            if key in props:
                errors.extend(validate(value, props[key], sub))
            elif schema.get("additionalProperties") is False:
                known = ", ".join(props) or "none"
                errors.append(f"{sub}: unknown key (allowed: {known})")
    return errors
