# Contributing

Thanks for helping. This project is small and the bar is simple: **be precise and
be honest about what the data can and cannot show.**

## Setup

```bash
git clone <your fork>
cd prop-rules-checker
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

## Ground rules

- **No real account data in the repo.** Fixtures must be synthetic or fully
  anonymised, and say so (file name starting with `synthetic_` or a comment).
- **No claims about specific firms.** Presets are illustrative examples and must
  keep the "ILLUSTRATIVE EXAMPLE ONLY" header. Don't name real firms in presets,
  docs or tests. Users write their own rule files from their firm's current terms.
- **Every assumption is visible.** If a rule has to approximate (for example
  equity from closed trades), the report must say so via `Report.assumptions` or
  `RuleResult.approximated`, and the README rule reference must describe it.
- **Tests for edge cases.** Rule changes need tests for boundaries: exactly at
  the limit, day rollover in a non-UTC zone, DST changes, same-timestamp events.

## Adding a platform format

1. Open a "New platform / export format" issue with an anonymised header and rows,
   and links to any official docs.
2. Add a parser in `src/prop_rules_checker/parsers/`, match columns **by name**,
   and raise `InputError` with an actionable message when something is missing.
3. Register it in `FORMATS` and `detect_format` (`parsers/__init__.py`).
4. Add a synthetic fixture and tests, and update "Supported formats" in the README,
   including what was verified and against what.

## Adding a rule

1. Extend `RULES_SCHEMA` in `schema.py`, regenerate `schema/rules.schema.json`:
   `python -c "import json; from prop_rules_checker.schema import RULES_SCHEMA as s; print(json.dumps(s, indent=2))" > schema/rules.schema.json`
2. Add defaults in `rules.py` and the check function in `checks.py`.
3. Document it in the README rule reference and add a CHANGELOG entry.

## Pull requests

Keep PRs focused; describe how you tested. CI runs ruff and pytest on Python
3.10-3.13. By contributing you agree your work is released under the MIT License
and you follow the [Code of Conduct](CODE_OF_CONDUCT.md).
