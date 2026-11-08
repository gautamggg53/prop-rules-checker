"""Command-line interface: ``prop-rules-check``.

Exit codes: 0 = no violations, 1 = at least one violation, 2 = input error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from importlib.resources import as_file, files
from pathlib import Path

from . import __version__
from .checks import check
from .models import InputError
from .news import load_news
from .parsers import FORMATS, load_trades
from .report import render_text
from .rules import list_presets, load_rules

DEMO_PRESET = "example-1step-trailing"

EXIT_OK, EXIT_VIOLATIONS, EXIT_INPUT_ERROR = 0, 1, 2


def _warn_at(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number such as 0.8") from exc
    if value > 1:
        value /= 100  # allow --warn-at 80
    if not 0 < value <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1 (e.g. 0.8 for 80%)")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prop-rules-check",
        description="Check a trade history against prop-firm style rules and flag "
        "violations and near-misses. Not financial advice; not affiliated with "
        "any firm.",
        epilog="Exit codes: 0 no violations, 1 violations found, 2 input error.",
    )
    p.add_argument("trades", nargs="?", help="trade history file (HTML or CSV export)")
    p.add_argument("-r", "--rules", help="rule set (YAML/JSON path or bundled preset name)")
    p.add_argument(
        "-f",
        "--format",
        default="auto",
        choices=["auto", *FORMATS],
        help="input format (default: auto-detect)",
    )
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument(
        "--warn-at",
        type=_warn_at,
        default=None,
        metavar="FRACTION",
        help="near-miss threshold as a fraction of a limit (default 0.8)",
    )
    p.add_argument("--news", metavar="CSV", help="news events CSV for the news-trading rule")
    p.add_argument(
        "--news-tz",
        default="UTC",
        metavar="TZ",
        help="timezone of naive times in the news file (default UTC)",
    )
    p.add_argument(
        "--source-tz",
        default="UTC",
        metavar="TZ",
        help="timezone of naive timestamps in the trade file, e.g. your MT4/MT5 "
        "server zone (default UTC)",
    )
    p.add_argument(
        "--date-format", metavar="STRPTIME", help="explicit date format, e.g. '%%m/%%d/%%Y %%H:%%M'"
    )
    p.add_argument("--symbol", help="symbol for exports without one (TradingView strategy)")
    p.add_argument("--list-presets", action="store_true", help="list bundled example presets")
    p.add_argument("--list-formats", action="store_true", help="list supported input formats")
    p.add_argument(
        "--demo",
        action="store_true",
        help="check the bundled synthetic history (no trades file; not a real account)",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _demo_banner(rules: str) -> str:
    return f"Demo: synthetic trades bundled with this install (not a real account), preset {rules}."


def _run(args: argparse.Namespace, trades_path: str, *, demo: bool) -> int:
    if demo and args.json:
        print(_demo_banner(args.rules), file=sys.stderr)
    elif demo:
        print(_demo_banner(args.rules))
        print()
    try:
        rules = load_rules(args.rules)
        history = load_trades(
            trades_path,
            args.format,
            source_tz=args.source_tz,
            date_format=args.date_format,
            symbol=args.symbol,
        )
        news = (
            load_news(args.news, tz=args.news_tz, date_format=args.date_format)
            if args.news
            else None
        )
        report = check(history, rules, news=news, warn_at=args.warn_at)
    except InputError as exc:
        print(f"prop-rules-check: input error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    print(report.to_json() if args.json else render_text(report))
    return EXIT_VIOLATIONS if report.has_violations else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_presets:
        print("\n".join(list_presets()))
        return EXIT_OK
    if args.list_formats:
        for name, desc in FORMATS.items():
            print(f"{name:<18} {desc}")
        return EXIT_OK
    if args.demo:
        if args.trades:
            print(
                "prop-rules-check: --demo uses the bundled synthetic file and does not "
                "take a trades path",
                file=sys.stderr,
            )
            return EXIT_INPUT_ERROR
        if not args.rules:
            args.rules = DEMO_PRESET
        resource = files("prop_rules_checker").joinpath("data", "synthetic_quickstart.csv")
        if not resource.is_file():
            print(
                "prop-rules-check: input error: the bundled synthetic demo file is missing "
                "from this install",
                file=sys.stderr,
            )
            return EXIT_INPUT_ERROR
        with as_file(resource) as path:
            return _run(args, str(Path(path)), demo=True)
    if not args.trades or not args.rules:
        parser.print_usage(sys.stderr)
        print("prop-rules-check: error: a trades file and --rules are required", file=sys.stderr)
        return EXIT_INPUT_ERROR
    return _run(args, args.trades, demo=False)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
