"""The rule engine: :func:`check` turns trades + a rule set into a :class:`Report`."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from .models import NewsEvent, Trade, TradeHistory
from .news import _clean, event_applies
from .parsers.common import get_tz
from .report import Finding, Report, RuleResult, Status, money, worst
from .rules import RuleSet

EPS = 1e-6
DEFAULT_WARN_AT = 0.8


@dataclass(frozen=True)
class _Point:
    time: datetime
    value: float
    kind: str  # "balance" (after a close) or "equity" (estimated low before a close)
    trade_id: str


def _grade(used: float, limit: float, warn_at: float) -> Status:
    if used > limit + EPS:
        return Status.FAIL
    if used >= warn_at * limit - EPS:
        return Status.WARN
    return Status.PASS


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _amount(cfg: dict[str, Any], reference: float) -> float:
    if "limit_amount" in cfg:
        return float(cfg["limit_amount"])
    return float(cfg["limit_pct"]) / 100.0 * reference


class _Context:
    def __init__(
        self,
        trades: list[Trade],
        rules: RuleSet,
        warn_at: float,
        news: list[NewsEvent] | None,
        volume_unit: str,
    ):
        self.rules = rules
        self.cur = rules.currency
        self.warn_at = warn_at
        self.news = news
        self.volume_unit = volume_unit
        self.trades = sorted(trades, key=lambda t: t.close_time)
        self.tz = get_tz(rules.day_reset_timezone)
        rt = rules.day_reset_time
        self.reset = timedelta(hours=rt.hour, minutes=rt.minute)
        self.points = self._ledger()
        self.has_mae = any(t.mae is not None for t in self.trades)

    def day(self, dt: datetime) -> date:
        """Trading-day label. A session that starts at or after noon (e.g. 17:00) is
        labelled with the date it ends on, otherwise with the date it starts on."""
        d = (dt.astimezone(self.tz) - self.reset).date()
        return d + timedelta(days=1) if self.reset >= timedelta(hours=12) else d

    def m(self, v: float) -> str:
        return money(v, self.cur)

    def _ledger(self) -> list[_Point]:
        """Balance after every close, preceded by an estimated equity low where MAE is known.

        The estimate at a close is ``balance before the close + sum of the adverse
        excursions of every trade still open at that moment``. Each trade's worst
        floating loss is assumed to coincide, so the estimate is conservative.
        """
        by_open = sorted(
            (t for t in self.trades if t.mae is not None and t.open_time), key=lambda t: t.open_time
        )  # type: ignore[arg-type, return-value]
        nxt = 0
        active: dict[int, float] = {}
        processed: set[int] = set()
        bal = self.rules.initial_balance
        points: list[_Point] = []
        for t in self.trades:
            while nxt < len(by_open) and by_open[nxt].open_time <= t.close_time:  # type: ignore
                o = by_open[nxt]
                nxt += 1
                if id(o) not in processed:
                    active[id(o)] = o.mae or 0.0
            extra = t.mae if (t.mae is not None and t.open_time is None) else 0.0
            floating = sum(active.values()) + extra
            if floating < 0:
                points.append(_Point(t.close_time, bal + floating, "equity", t.id))
            bal += t.pnl
            points.append(_Point(t.close_time, bal, "balance", t.id))
            processed.add(id(t))
            active.pop(id(t), None)
        return points

    def series(self, measure: str) -> list[_Point]:
        if measure == "equity":
            return self.points
        return [p for p in self.points if p.kind == "balance"]


# --------------------------------------------------------------------------- rules


def _daily_loss(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    use_eq = cfg["measure"] == "equity"
    bal = ctx.rules.initial_balance
    days: dict[date, dict[str, Any]] = {}
    for p in ctx.points:
        d = ctx.day(p.time)
        if d not in days:
            ref = ctx.rules.initial_balance if cfg["reference"] == "initial_balance" else bal
            days[d] = {
                "start": bal,
                "low": bal,
                "low_time": None,
                "low_id": None,
                "limit": _amount(cfg, ref),
                "breach_time": None,
                "breach_id": None,
            }
        info = days[d]
        if p.kind == "balance" or use_eq:
            if p.value < info["low"]:
                info.update(low=p.value, low_time=p.time, low_id=p.trade_id)
            if info["breach_time"] is None and info["start"] - p.value > info["limit"] + EPS:
                info.update(breach_time=p.time, breach_id=p.trade_id)
        if p.kind == "balance":
            bal = p.value
    findings: list[Finding] = []
    worst_day, worst_usage = None, -1.0
    table = []
    for d, info in days.items():
        loss = info["start"] - info["low"]
        usage = loss / info["limit"]
        status = _grade(loss, info["limit"], ctx.warn_at)
        table.append(
            {
                "day": d,
                "start_balance": info["start"],
                "lowest": info["low"],
                "loss": loss,
                "limit": info["limit"],
                "usage": usage,
                "status": status.value,
            }
        )
        if usage > worst_usage:
            worst_day, worst_usage = d, usage
        if status is not Status.PASS:
            when = info["breach_time"] or info["low_time"]
            tid = info["breach_id"] or info["low_id"]
            findings.append(
                Finding(
                    status,
                    f"{d}: down {ctx.m(loss)} from the day's start "
                    f"balance of {ctx.m(info['start'])}; limit "
                    f"{ctx.m(info['limit'])} ({_pct(usage)} used)",
                    when,
                    (tid,) if tid else (),
                    loss,
                    info["limit"],
                )
            )
    status = worst([f.status for f in findings])
    w = next(r for r in table if r["day"] == worst_day)
    summary = (
        f"worst day {worst_day}: {ctx.m(w['loss'])} of {ctx.m(w['limit'])} ({_pct(w['usage'])})"
    )
    return RuleResult(
        "daily_loss",
        "Daily loss limit",
        status,
        summary,
        findings,
        {"days": table},
        approximated=use_eq,
    )


def _max_drawdown(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    initial = ctx.rules.initial_balance
    amount = _amount(cfg, initial)
    floor = initial - amount
    pts = ctx.series(cfg["measure"])
    low = min([initial] + [p.value for p in pts])
    used = initial - low
    status = _grade(used, amount, ctx.warn_at)
    findings = []
    if status is not Status.PASS:
        first = next(
            p
            for p in pts
            if (
                initial - p.value > amount + EPS
                if status is Status.FAIL
                else initial - p.value >= ctx.warn_at * amount - EPS
            )
        )
        verb = "fell below" if status is Status.FAIL else "came within reach of"
        findings.append(
            Finding(
                status,
                f"{'equity (est.)' if first.kind == 'equity' else 'balance'}"
                f" {ctx.m(first.value)} {verb} the floor of {ctx.m(floor)} after "
                f"trade {first.trade_id}",
                first.time,
                (first.trade_id,),
                first.value,
                floor,
            )
        )
    summary = f"lowest {ctx.m(low)}, floor {ctx.m(floor)} ({_pct(used / amount)} used)"
    return RuleResult(
        "max_drawdown",
        "Max drawdown (static)",
        status,
        summary,
        findings,
        {"floor": floor, "lowest": low, "usage": used / amount},
        approximated=cfg["measure"] == "equity",
    )


def _trailing(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    initial = ctx.rules.initial_balance
    amount = _amount(cfg, initial)
    lock = cfg.get("lock_at")
    lock_level = initial if lock == "initial_balance" else (float(lock) if lock else None)
    hwm = initial
    findings: list[Finding] = []
    max_usage, floor = 0.0, initial - amount
    locked_at: datetime | None = None
    warned = False
    for p in ctx.series(cfg["measure"]):
        floor = hwm - amount
        if lock_level is not None and floor >= lock_level - EPS:
            floor = lock_level
        allowed = hwm - floor
        used = hwm - p.value
        status = _grade(used, allowed, ctx.warn_at)
        max_usage = max(max_usage, used / allowed)
        if status is Status.FAIL and not any(f.status is Status.FAIL for f in findings):
            findings.append(
                Finding(
                    status,
                    f"{'equity (est.)' if p.kind == 'equity' else 'balance'}"
                    f" {ctx.m(p.value)} fell below the trailing floor of "
                    f"{ctx.m(floor)} (high-water mark {ctx.m(hwm)}) after trade "
                    f"{p.trade_id}",
                    p.time,
                    (p.trade_id,),
                    p.value,
                    floor,
                )
            )
        elif status is Status.WARN and not warned:
            warned = True
            findings.append(
                Finding(
                    status,
                    f"balance {ctx.m(p.value)} came within "
                    f"{ctx.m(p.value - floor)} of the trailing floor "
                    f"{ctx.m(floor)} after trade {p.trade_id}",
                    p.time,
                    (p.trade_id,),
                    p.value,
                    floor,
                )
            )
        if p.kind == "balance" and p.value > hwm:
            hwm = p.value
            if lock_level is not None and locked_at is None and hwm - amount >= lock_level - EPS:
                locked_at = p.time
    final_floor = hwm - amount
    if lock_level is not None and final_floor >= lock_level - EPS:
        final_floor = lock_level
    status = worst([f.status for f in findings])
    lock_text = f", locked at {ctx.m(lock_level)}" if locked_at else ""
    summary = (
        f"high-water {ctx.m(hwm)}, current floor {ctx.m(final_floor)}{lock_text} "
        f"(max {_pct(max_usage)} used)"
    )
    return RuleResult(
        "trailing_drawdown",
        "Trailing drawdown",
        status,
        summary,
        findings,
        {
            "high_water_mark": hwm,
            "floor": final_floor,
            "max_usage": max_usage,
            "locked_at": locked_at,
        },
        approximated=cfg["measure"] == "equity",
    )


def _profit_target(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    initial = ctx.rules.initial_balance
    target = (
        float(cfg["target_amount"])
        if "target_amount" in cfg
        else (float(cfg["target_pct"]) / 100 * initial)
    )
    bal_pts = ctx.series("balance")
    final = bal_pts[-1].value if bal_pts else initial
    profit = final - initial
    hit = next((p for p in bal_pts if p.value - initial >= target - EPS), None)
    progress = profit / target
    if profit >= target - EPS:
        status, summary = Status.PASS, f"reached: {ctx.m(profit)} of {ctx.m(target)}"
    else:
        status = Status.PENDING
        summary = f"{ctx.m(profit)} of {ctx.m(target)} ({_pct(max(progress, 0))})"
        if hit:
            summary += f"; was reached on {ctx.day(hit.time)} but balance has since dropped"
    return RuleResult(
        "profit_target",
        "Profit target",
        status,
        summary,
        [],
        {
            "target": target,
            "profit": profit,
            "progress": progress,
            "first_reached": hit.time if hit else None,
        },
    )


def _day_pnl(ctx: _Context) -> dict[date, float]:
    out: dict[date, float] = {}
    for t in ctx.trades:
        d = ctx.day(t.close_time)
        out[d] = out.get(d, 0.0) + t.pnl
    return out


def _consistency(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    by_day = _day_pnl(ctx)
    net = sum(by_day.values())
    positive = sum(v for v in by_day.values() if v > 0)
    denom = net if cfg["denominator"] == "net_profit" else positive
    label = "net profit" if cfg["denominator"] == "net_profit" else "sum of winning days"
    limit = float(cfg["max_best_day_pct"]) / 100
    best_day = max(by_day, key=lambda d: by_day[d])
    best = by_day[best_day]
    metrics: dict[str, Any] = {
        "best_day": best_day,
        "best_day_pnl": best,
        "denominator": denom,
        "net_profit": net,
        "winning_days_total": positive,
    }
    if best <= EPS or denom <= EPS:
        return RuleResult(
            "consistency",
            "Consistency (best day)",
            Status.INFO,
            f"not applicable: {label} is {ctx.m(denom)}",
            [],
            metrics,
        )
    ratio = best / denom
    metrics["ratio"] = ratio
    status = _grade(ratio, limit, ctx.warn_at)
    summary = (
        f"best day {best_day} = {ctx.m(best)}, {_pct(ratio)} of {label} "
        f"{ctx.m(denom)} (max {_pct(limit)})"
    )
    findings = []
    if status is Status.FAIL:
        needed = best / limit - denom
        metrics["additional_profit_needed"] = needed
        findings.append(
            Finding(
                status,
                f"{summary}; about {ctx.m(needed)} more profit on other "
                "days would bring it within the limit",
                None,
                (),
                ratio,
                limit,
            )
        )
    elif status is Status.WARN:
        findings.append(Finding(status, summary, None, (), ratio, limit))
    return RuleResult("consistency", "Consistency (best day)", status, summary, findings, metrics)


def _min_days(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    need = int(cfg["days"])
    days: set[date] = set()
    for t in ctx.trades:
        if not t.is_trade:
            continue
        if cfg["count_by"] in ("open", "any") and t.open_time is not None:
            days.add(ctx.day(t.open_time))
        if cfg["count_by"] in ("close", "any") or t.open_time is None:
            days.add(ctx.day(t.close_time))
    have = len(days)
    status = Status.PASS if have >= need else Status.PENDING
    summary = f"{have} trading day(s), minimum {need}"
    if status is Status.PENDING:
        summary += f" ({need - have} more needed)"
    return RuleResult(
        "min_trading_days",
        "Minimum trading days",
        status,
        summary,
        [],
        {"trading_days": sorted(days), "count": have, "required": need},
    )


def _news(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    if ctx.news is None:
        return RuleResult(
            "news_trading",
            "News trading window",
            Status.SKIPPED,
            "no news events file given (--news)",
        )
    before = timedelta(minutes=float(cfg["minutes_before"]))
    after = timedelta(minutes=float(cfg["minutes_after"]))
    buffer = timedelta(minutes=float(cfg["warn_buffer_minutes"]))
    impacts = {i.lower() for i in cfg["impacts"]}
    events = [e for e in ctx.news if not impacts or not e.impact or e.impact in impacts]
    findings: list[Finding] = []
    for t in ctx.trades:
        if not t.is_trade:
            continue
        stamps: list[tuple[str, datetime]] = []
        if "open" in cfg["check"] and t.open_time is not None:
            stamps.append(("opened", t.open_time))
        if "close" in cfg["check"]:
            stamps.append(("closed", t.close_time))
        for e in events:
            if not event_applies(e, t.symbol):
                continue
            start, end = e.time - before, e.time + after
            name = e.title or "news event"
            hit = False
            for verb, ts in stamps:
                delta = (ts - e.time).total_seconds() / 60
                rel = f"{abs(delta):.0f} min {'before' if delta < 0 else 'after'}"
                if start <= ts <= end:
                    hit = True
                    findings.append(
                        Finding(
                            Status.FAIL,
                            f"trade {t.id} ({t.symbol}) {verb} "
                            f"{rel} {name} at {e.time:%Y-%m-%d %H:%M} UTC",
                            ts,
                            (t.id,),
                        )
                    )
                elif buffer and start - buffer <= ts <= end + buffer:
                    hit = True
                    findings.append(
                        Finding(
                            Status.WARN,
                            f"trade {t.id} ({t.symbol}) {verb} "
                            f"{rel} {name} (just outside the window)",
                            ts,
                            (t.id,),
                        )
                    )
            held = t.open_time is not None and t.open_time < start and t.close_time > end
            if not hit and held and cfg["hold_through"] != "allow":
                st = Status.FAIL if cfg["hold_through"] == "forbid" else Status.WARN
                findings.append(
                    Finding(
                        st,
                        f"trade {t.id} ({t.symbol}) was held open through "
                        f"{name} at {e.time:%Y-%m-%d %H:%M} UTC",
                        e.time,
                        (t.id,),
                    )
                )
    status = worst([f.status for f in findings])
    n_fail = sum(f.status is Status.FAIL for f in findings)
    n_warn = sum(f.status is Status.WARN for f in findings)
    window = f"-{cfg['minutes_before']:g}/+{cfg['minutes_after']:g} min"
    summary = (
        f"{n_fail} trade time(s) inside a {window} window, {n_warn} warning(s); "
        f"{len(events)} event(s) checked"
    )
    return RuleResult(
        "news_trading",
        "News trading window",
        status,
        summary,
        findings,
        {"events_checked": len(events)},
    )


def _weekend(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    tz: tzinfo = get_tz(cfg["timezone"])
    fc = time(*map(int, cfg["friday_close"].split(":")))
    so = time(*map(int, cfg["sunday_open"].split(":")))
    warn = timedelta(minutes=float(cfg["warn_within_minutes"]))
    exempt = [_clean(s) for s in cfg["exempt_symbols"]]
    findings: list[Finding] = []
    unknown = 0
    held_ids: list[str] = []
    for t in ctx.trades:
        if not t.is_trade or any(_clean(t.symbol).startswith(x) for x in exempt if x):
            continue
        if t.open_time is None:
            unknown += 1
            continue
        local_open = t.open_time.astimezone(tz)
        friday = local_open.date() - timedelta(days=(local_open.weekday() - 4) % 7)
        while True:
            w_start = datetime.combine(friday, fc, tzinfo=tz)
            w_end = datetime.combine(friday + timedelta(days=2), so, tzinfo=tz)
            if w_start > t.close_time + warn:
                break
            if t.open_time < w_end and t.close_time > w_start:
                held_ids.append(t.id)
                st = Status.INFO if cfg["allowed"] else Status.FAIL
                findings.append(
                    Finding(
                        st,
                        f"trade {t.id} ({t.symbol}) was open over the "
                        f"weekend of {friday} (market close "
                        f"{cfg['friday_close']} {cfg['timezone']})",
                        w_start,
                        (t.id,),
                    )
                )
                break
            if (
                not cfg["allowed"]
                and warn
                and t.open_time < w_start
                and w_start - warn <= t.close_time <= w_start
            ):
                mins = (w_start - t.close_time).total_seconds() / 60
                findings.append(
                    Finding(
                        Status.WARN,
                        f"trade {t.id} ({t.symbol}) closed {mins:.0f} min before the Friday close",
                        t.close_time,
                        (t.id,),
                    )
                )
                break
            friday += timedelta(days=7)
    status = worst([f.status for f in findings if f.status is not Status.INFO])
    if cfg["allowed"]:
        summary = f"allowed; {len(held_ids)} trade(s) held over a weekend"
        status = Status.INFO if held_ids else Status.PASS
    else:
        summary = f"{len(held_ids)} trade(s) held over a weekend"
    if unknown:
        summary += f"; {unknown} trade(s) without an open time not checked"
        if status is Status.PASS and unknown == sum(t.is_trade for t in ctx.trades):
            status = Status.SKIPPED
    return RuleResult(
        "weekend_holding",
        "Weekend holding",
        status,
        summary,
        findings,
        {"held_trade_ids": held_ids, "unchecked": unknown},
    )


def _lots(ctx: _Context, cfg: dict[str, Any]) -> RuleResult:
    findings: list[Finding] = []
    parts: list[str] = []
    metrics: dict[str, Any] = {}
    trades = [t for t in ctx.trades if t.is_trade]
    unit = "lots" if ctx.volume_unit == "lots" else ctx.volume_unit
    if "max_lots_per_trade" in cfg:
        limit = float(cfg["max_lots_per_trade"])
        biggest = max((t.volume for t in trades), default=0.0)
        metrics["largest_trade"] = biggest
        for t in trades:
            st = _grade(t.volume, limit, ctx.warn_at)
            if st is not Status.PASS:
                findings.append(
                    Finding(
                        st,
                        f"trade {t.id} ({t.symbol}) {t.volume:g} {unit} vs max {limit:g}",
                        t.open_time or t.close_time,
                        (t.id,),
                        t.volume,
                        limit,
                    )
                )
        parts.append(f"largest trade {biggest:g} {unit} (max {limit:g})")
    if "max_open_lots" in cfg:
        limit = float(cfg["max_open_lots"])
        events: list[tuple[datetime, int, float, str]] = []
        for t in trades:
            if t.open_time is None:
                continue
            events.append((t.open_time, 1, t.volume, t.id))
            events.append((t.close_time, 0, -t.volume, t.id))
        events.sort(key=lambda e: (e[0], e[1]))  # closes before opens at the same instant
        cur, peak, peak_time = 0.0, 0.0, None
        open_ids: set[str] = set()
        peak_ids: tuple[str, ...] = ()
        for when, is_open, vol, tid in events:
            cur += vol
            if is_open:
                open_ids.add(tid)
            else:
                open_ids.discard(tid)
            if cur > peak + EPS:
                peak, peak_time, peak_ids = cur, when, tuple(sorted(open_ids))
        metrics["peak_open"] = peak
        st = _grade(peak, limit, ctx.warn_at)
        if st is not Status.PASS:
            findings.append(
                Finding(
                    st,
                    f"{peak:g} {unit} open at once (max {limit:g}) at "
                    f"{peak_time:%Y-%m-%d %H:%M} UTC",
                    peak_time,
                    peak_ids,
                    peak,
                    limit,
                )
            )
        parts.append(f"peak open {peak:g} {unit} (max {limit:g})")
    return RuleResult(
        "lot_size",
        "Lot size",
        worst([f.status for f in findings]),
        "; ".join(parts),
        findings,
        metrics,
    )


_RULES = {
    "daily_loss": _daily_loss,
    "max_drawdown": _max_drawdown,
    "trailing_drawdown": _trailing,
    "profit_target": _profit_target,
    "consistency": _consistency,
    "min_trading_days": _min_days,
    "news_trading": _news,
    "weekend_holding": _weekend,
    "lot_size": _lots,
}


def check(
    trades: TradeHistory | Iterable[Trade],
    rules: RuleSet,
    news: list[NewsEvent] | None = None,
    warn_at: float | None = None,
) -> Report:
    """Evaluate ``trades`` against ``rules`` and return a :class:`Report`."""
    if isinstance(trades, TradeHistory):
        history = trades
    else:
        history = TradeHistory(trades=list(trades), format="python")
    if not history.trades:
        raise ValueError("no trades to check")
    level = warn_at if warn_at is not None else (rules.warn_at or DEFAULT_WARN_AT)
    if not 0 < level <= 1:
        raise ValueError("warn_at must be in (0, 1]")
    ctx = _Context(history.trades, rules, level, news, history.volume_unit)
    results = [_RULES[name](ctx, cfg) for name, cfg in rules.rules.items()]
    rt = rules.day_reset_time
    assumptions = [
        f"Balance starts at {ctx.m(rules.initial_balance)} (from the rule set) and moves only "
        "with closed-trade P/L; deposits, withdrawals and positions still open at export time "
        "are not included.",
        f"A trading day runs from {rt:%H:%M} to {rt:%H:%M} in {rules.day_reset_timezone}"
        + (" and is labelled with the date it ends on" if rt.hour >= 12 else "")
        + "; each trade's P/L counts on the day it closed.",
        "Touching a limit exactly is a warning; only going beyond it is a violation.",
    ]
    if any(r.approximated for r in results):
        if ctx.has_mae:
            assumptions.append(
                "Equity-based limits are estimated: at each close, balance plus the worst "
                "adverse excursion of every trade open at that moment (assumed to coincide). "
                "This is conservative but cannot see equity between closes exactly."
            )
        else:
            assumptions.append(
                "Equity-based limits were checked against closed balance only: the export has "
                "no intraday equity or adverse-excursion data. A floating loss that breached an "
                "equity limit before the trade closed would NOT show here."
            )
    assumptions.extend(history.notes)
    first_open = min((t.open_time for t in ctx.trades if t.open_time), default=None)
    start = min(filter(None, [first_open, ctx.trades[0].close_time]))
    final = ctx.series("balance")[-1].value
    return Report(
        rules_name=rules.name,
        currency=rules.currency,
        initial_balance=rules.initial_balance,
        final_balance=final,
        trade_count=sum(t.is_trade for t in ctx.trades),
        source_format=history.format,
        period_start=start,
        period_end=ctx.trades[-1].close_time,
        warn_at=level,
        results=results,
        assumptions=assumptions,
    )
