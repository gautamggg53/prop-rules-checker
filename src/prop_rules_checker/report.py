"""Report data structures and renderers (plain text and JSON)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class Status(str, Enum):
    FAIL = "fail"  # rule broken
    WARN = "warn"  # near-miss: within the warn threshold of a limit (or at it)
    PENDING = "pending"  # objective not reached yet (profit target, minimum days)
    INFO = "info"  # informational / not applicable
    PASS = "pass"
    SKIPPED = "skipped"  # could not be evaluated with the data given


SEVERITY = {
    Status.FAIL: 5,
    Status.WARN: 4,
    Status.PENDING: 3,
    Status.INFO: 2,
    Status.PASS: 1,
    Status.SKIPPED: 0,
}


def worst(statuses: list[Status], default: Status = Status.PASS) -> Status:
    return max(statuses, key=lambda s: SEVERITY[s]) if statuses else default


@dataclass
class Finding:
    status: Status
    message: str
    time: datetime | None = None
    trade_ids: tuple[str, ...] = ()
    value: float | None = None
    limit: float | None = None


@dataclass
class RuleResult:
    rule: str
    title: str
    status: Status
    summary: str
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    approximated: bool = False


@dataclass
class Report:
    rules_name: str
    currency: str
    initial_balance: float
    final_balance: float
    trade_count: int
    source_format: str
    period_start: datetime | None
    period_end: datetime | None
    warn_at: float
    results: list[RuleResult]
    assumptions: list[str]
    limitations: list[str] = field(default_factory=list)

    @property
    def violations(self) -> list[RuleResult]:
        return [r for r in self.results if r.status is Status.FAIL]

    @property
    def warnings(self) -> list[RuleResult]:
        return [r for r in self.results if r.status is Status.WARN]

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def result(self, rule: str) -> RuleResult:
        for r in self.results:
            if r.rule == rule:
                return r
        raise KeyError(rule)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(
            {
                "rules_name": self.rules_name,
                "currency": self.currency,
                "initial_balance": self.initial_balance,
                "final_balance": self.final_balance,
                "net_pnl": self.final_balance - self.initial_balance,
                "trade_count": self.trade_count,
                "source_format": self.source_format,
                "period_start": self.period_start,
                "period_end": self.period_end,
                "warn_at": self.warn_at,
                "status": worst([r.status for r in self.results]).value,
                "violations": len(self.violations),
                "warnings": len(self.warnings),
                "results": [
                    {
                        "rule": r.rule,
                        "title": r.title,
                        "status": r.status.value,
                        "summary": r.summary,
                        "approximated": r.approximated,
                        "metrics": r.metrics,
                        "findings": [
                            {
                                "status": f.status.value,
                                "message": f.message,
                                "time": f.time,
                                "trade_ids": list(f.trade_ids),
                                "value": f.value,
                                "limit": f.limit,
                            }
                            for f in r.findings
                        ],
                    }
                    for r in self.results
                ],
                "limitations": self.limitations,
                "assumptions": self.assumptions,
            }
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, Enum):
        return obj.value
    return obj


def money(value: float, currency: str = "") -> str:
    text = f"{value:,.2f}"
    return f"{text} {currency}".strip()


_LABEL = {
    Status.FAIL: "FAIL",
    Status.WARN: "WARN",
    Status.PENDING: "PENDING",
    Status.INFO: "INFO",
    Status.PASS: "PASS",
    Status.SKIPPED: "SKIPPED",
}


def render_text(report: Report, *, max_findings: int = 10) -> str:
    lines: list[str] = []
    span = ""
    if report.period_start and report.period_end:
        span = f", {report.period_start:%Y-%m-%d} to {report.period_end:%Y-%m-%d} UTC"
    lines.append(f"Rule set: {report.rules_name}")
    lines.append(f"Trades:   {report.trade_count} ({report.source_format}{span})")
    lines.append(
        f"Balance:  {money(report.initial_balance, report.currency)} -> "
        f"{money(report.final_balance, report.currency)} "
        f"(net {report.final_balance - report.initial_balance:+,.2f})"
    )
    if report.limitations:
        lines.append("")
        lines.append("Closed-trade limits (a PASS does not prove these):")
        lines.extend(f"  - {item}" for item in report.limitations)
    lines.append("")
    width = max(len(r.title) for r in report.results)
    lines.append(f"{'RULE':<{width}}  {'STATUS':<8} DETAIL")
    for r in report.results:
        mark = "*" if r.approximated else ""
        lines.append(f"{r.title:<{width}}  {_LABEL[r.status] + mark:<8} {r.summary}")
    flagged = [
        (r, f) for r in report.results for f in r.findings if f.status in (Status.FAIL, Status.WARN)
    ]
    if flagged:
        lines.append("")
        lines.append("Findings:")
        for r, f in flagged[:max_findings]:
            lines.append(f"  [{_LABEL[f.status]}] {r.title}: {f.message}")
        if len(flagged) > max_findings:
            lines.append(f"  ... {len(flagged) - max_findings} more (use --json for all)")
    if any(r.approximated for r in report.results):
        lines.append("")
        lines.append(
            "* equity-based limit approximated from closed-trade data (see the limits above)"
        )
    lines.append("")
    lines.append("Assumptions and limitations:")
    hoisted = set(report.limitations)
    rest = [a for a in report.assumptions if a not in hoisted]
    lines.extend(f"  - {a}" for a in rest)
    lines.append("")
    v, w = len(report.violations), len(report.warnings)
    verdict = f"{v} violation(s), {w} near-miss warning(s)"
    lines.append(f"Result: {verdict}. Check your firm's current rules; this is not advice.")
    return "\n".join(lines)
