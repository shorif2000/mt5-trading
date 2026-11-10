"""Backtest metrics and a Markdown report. Results are descriptive, never a profitability claim."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading.backtest.engine import BacktestResult, Outcome, TradeRecord

NEW_YORK = ZoneInfo("America/New_York")
MINIMUM_TRADES_FOR_EVIDENCE = 30


def session_of(trade: TradeRecord) -> str:
    hour = trade.entry_time.astimezone(NEW_YORK).hour
    if 8 <= hour < 17:
        return "New York (08:00-17:00 NY)"
    if 3 <= hour < 8:
        return "London (03:00-08:00 NY)"
    return "Asia (19:00-03:00 NY)"


@dataclass(frozen=True)
class Metrics:
    signals: int
    outcomes: dict[str, int]
    filter_reasons: dict[str, int]
    risk_rejections: int
    minimum_volume_rejections: int
    margin_rejections: int
    executable: int
    executable_at_minimum_volume: int
    trades: int
    wins: int
    win_rate: float | None
    gross_gbp: Decimal
    net_gbp: Decimal
    profit_factor: float | None
    average_win: Decimal | None
    average_loss: Decimal | None
    expected_value: Decimal | None
    max_drawdown_gbp: Decimal
    max_drawdown_percent: float
    max_consecutive_losses: int
    average_holding: timedelta | None
    spread_cost: Decimal
    commission_cost: Decimal
    slippage_cost: Decimal
    by_session: dict[str, tuple[int, Decimal]]
    by_month: dict[str, tuple[int, Decimal]]
    exit_reasons: dict[str, int]
    final_balance: Decimal
    losses_above_risk_limit: int  # only possible when price gaps through the stop


def metrics(result: BacktestResult) -> Metrics:
    outcomes = Counter(s.outcome.value for s in result.signals)
    filters = Counter(s.reasons[0] for s in result.signals if s.outcome == Outcome.FILTERED)
    trades = result.trades
    wins = [t.net_gbp for t in trades if t.net_gbp > 0]
    losses = [t.net_gbp for t in trades if t.net_gbp <= 0]
    peak = balance = result.starting_balance
    drawdown, drawdown_pct, streak, worst_streak = Decimal(0), 0.0, 0, 0
    for trade in trades:
        balance = trade.balance_after
        peak = max(peak, balance)
        if peak - balance > drawdown:
            drawdown, drawdown_pct = peak - balance, float((peak - balance) / peak * 100)
        streak = streak + 1 if trade.net_gbp <= 0 else 0
        worst_streak = max(worst_streak, streak)
    by_session: dict[str, list[Decimal]] = defaultdict(list)
    by_month: dict[str, list[Decimal]] = defaultdict(list)
    for trade in trades:
        by_session[session_of(trade)].append(trade.net_gbp)
        by_month[trade.entry_time.astimezone(NEW_YORK).strftime("%Y-%m")].append(trade.net_gbp)
    # Gross = before all costs: spread and slippage are inside the fill prices, so add them back.
    gross = sum(
        (t.net_gbp + t.commission_gbp + t.spread_cost_gbp + t.slippage_cost_gbp for t in trades),
        Decimal(0),
    )
    executable = [s for s in result.signals if s.outcome == Outcome.EXECUTABLE]
    return Metrics(
        signals=len(result.signals),
        outcomes=dict(outcomes),
        filter_reasons=dict(filters.most_common()),
        risk_rejections=outcomes.get(Outcome.RISK_REJECTED.value, 0),
        minimum_volume_rejections=sum(
            1 for s in result.signals if s.minimum_volume_loss is not None
        ),
        margin_rejections=outcomes.get(Outcome.MARGIN_REJECTED.value, 0),
        executable=len(executable),
        executable_at_minimum_volume=sum(1 for s in executable if s.volume == Decimal("0.01")),
        trades=len(trades),
        wins=len(wins),
        win_rate=len(wins) / len(trades) if trades else None,
        gross_gbp=gross,
        net_gbp=sum((t.net_gbp for t in trades), Decimal(0)),
        profit_factor=float(sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
        average_win=sum(wins, Decimal(0)) / len(wins) if wins else None,
        average_loss=sum(losses, Decimal(0)) / len(losses) if losses else None,
        expected_value=sum((t.net_gbp for t in trades), Decimal(0)) / len(trades)
        if trades
        else None,
        max_drawdown_gbp=drawdown,
        max_drawdown_percent=drawdown_pct,
        max_consecutive_losses=worst_streak,
        average_holding=(
            sum((t.exit_time - t.entry_time for t in trades), timedelta()) / len(trades)
            if trades
            else None
        ),
        spread_cost=sum((t.spread_cost_gbp for t in trades), Decimal(0)),
        commission_cost=sum((t.commission_gbp for t in trades), Decimal(0)),
        slippage_cost=sum((t.slippage_cost_gbp for t in trades), Decimal(0)),
        by_session={k: (len(v), sum(v, Decimal(0))) for k, v in sorted(by_session.items())},
        by_month={k: (len(v), sum(v, Decimal(0))) for k, v in sorted(by_month.items())},
        exit_reasons=dict(Counter(t.exit_reason for t in trades).most_common()),
        final_balance=result.final_balance,
        losses_above_risk_limit=sum(
            1 for t in trades if t.maximum_risk is not None and -t.net_gbp > t.maximum_risk
        ),
    )


def _money(value: Decimal | None) -> str:
    return "n/a" if value is None else f"£{value:,.2f}"


def verdict(m: Metrics) -> str:
    if m.trades < MINIMUM_TRADES_FOR_EVIDENCE:
        return f"INCONCLUSIVE: {m.trades} trades (fewer than {MINIMUM_TRADES_FOR_EVIDENCE})"
    if m.net_gbp < 0:
        return f"NEGATIVE: net {_money(m.net_gbp)} over {m.trades} trades in this period"
    return (
        "Positive in this period only; not evidence of profitability without out-of-sample review"
    )


def render_period(name: str, window: str, m: Metrics) -> str:
    lines = [f"### {name} ({window})", "", f"**Verdict:** {verdict(m)}", ""]
    lines += [
        "| Outcome | Count |",
        "|---|---|",
        f"| Signals generated | {m.signals} |",
        f"| Filtered by strategy rules | {m.outcomes.get('filtered', 0)} |",
        f"| Rejected by risk management | {m.risk_rejections} |",
        f"| &nbsp;&nbsp;of which minimum volume above 2% | {m.minimum_volume_rejections} |",
        f"| Rejected by margin | {m.margin_rejections} |",
        f"| Executable | {m.executable} |",
        f"| &nbsp;&nbsp;of which at the 0.01 minimum volume | {m.executable_at_minimum_volume} |",
        "",
    ]
    if m.filter_reasons:
        lines += [
            "Filter reasons: " + "; ".join(f"{r} ({n})" for r, n in m.filter_reasons.items()),
            "",
        ]
    win_rate = "n/a" if m.win_rate is None else f"{m.win_rate:.1%}"
    pf = "n/a" if m.profit_factor is None else f"{m.profit_factor:.2f}"
    holding = "n/a" if m.average_holding is None else str(m.average_holding).split(".")[0]
    lines += [
        "| Trade metric | Value |",
        "|---|---|",
        f"| Trades | {m.trades} ({m.wins} wins) |",
        f"| Win rate | {win_rate} |",
        f"| Gross (before spread, slippage, commission) / net | {_money(m.gross_gbp)} / "
        f"{_money(m.net_gbp)} |",
        f"| Profit factor | {pf} |",
        f"| Average win / loss | {_money(m.average_win)} / {_money(m.average_loss)} |",
        f"| Expected value per trade | {_money(m.expected_value)} |",
        f"| Maximum drawdown | {_money(m.max_drawdown_gbp)} ({m.max_drawdown_percent:.1f}%) |",
        f"| Maximum consecutive losses | {m.max_consecutive_losses} |",
        f"| Average holding time | {holding} |",
        f"| Costs: spread / commission / slippage | {_money(m.spread_cost)} / "
        f"{_money(m.commission_cost)} / {_money(m.slippage_cost)} |",
        f"| Final paper balance (from £100) | {_money(m.final_balance)} |",
        f"| Losses above the 2% limit (stop gaps) | {m.losses_above_risk_limit} |",
        "",
    ]
    if m.exit_reasons:
        lines += ["Exits: " + "; ".join(f"{r} ({n})" for r, n in m.exit_reasons.items()), ""]
    if m.by_session:
        lines += [
            "By session: "
            + "; ".join(f"{k}: {n} trades, {_money(v)}" for k, (n, v) in m.by_session.items()),
            "",
        ]
    if m.by_month:
        lines += [
            "By month: " + "; ".join(f"{k}: {n}, {_money(v)}" for k, (n, v) in m.by_month.items()),
            "",
        ]
    return "\n".join(lines)
