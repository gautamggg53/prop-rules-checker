"""prop-rules-checker: check a trade history against prop-firm style rules.

Library usage::

    from prop_rules_checker import load_trades, load_rules, check

    trades = load_trades("history.htm", source_tz="Europe/Athens")
    rules = load_rules("example-2step-challenge")
    report = check(trades, rules, warn_at=0.8)
    print(report.has_violations, report.to_json())
"""

from .checks import check
from .models import InputError, NewsEvent, Trade, TradeHistory
from .news import load_news
from .parsers import FORMATS, detect_format, load_trades
from .report import Finding, Report, RuleResult, Status, render_text
from .rules import RuleSet, list_presets, load_rules, rules_from_dict

__version__ = "0.1.0"

__all__ = [
    "FORMATS",
    "Finding",
    "InputError",
    "NewsEvent",
    "Report",
    "RuleResult",
    "RuleSet",
    "Status",
    "Trade",
    "TradeHistory",
    "__version__",
    "check",
    "detect_format",
    "list_presets",
    "load_news",
    "load_rules",
    "load_trades",
    "render_text",
    "rules_from_dict",
]
