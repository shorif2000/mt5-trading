"""Run the backtest (Version 1.0, or 1.1 with the real-yield filter) over the approved
chronological periods and write a report."""

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading.backtest.bars import Bar
from trading.backtest.engine import Backtest, BacktestConfig, BacktestResult, MarginProvider
from trading.backtest.history_bars import coverage
from trading.backtest.real_yield import RealYieldFilter
from trading.backtest.report import metrics, render_period
from trading.market_data.sessions import MarketCalendar
from trading.models import InstrumentSpec

# Approved periods (owner decision): training, validation, out of sample.
PERIODS = (
    ("Training", datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
    ("Validation", datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
    ("Out of sample", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)),
)


def run_periods(
    *,
    m15: Sequence[Bar],
    h1: Sequence[Bar],
    conversion_m15: Sequence[Bar],
    spec: InstrumentSpec,
    conversion_spec: InstrumentSpec,
    calendar: MarketCalendar,
    config: BacktestConfig,
    margin_provider: MarginProvider | None,
    cost_notes: Sequence[str],
    version: str = "1.0",
) -> tuple[str, list[tuple[str, BacktestResult]]]:
    results = []
    for name, start, end in PERIODS:
        period_config = dataclasses.replace(config, trade_from=start, trade_until=end)
        backtest = Backtest(
            m15=m15,
            h1=h1,
            conversion_m15=conversion_m15,
            spec=spec,
            conversion_spec=conversion_spec,
            calendar=calendar,
            config=period_config,
            margin_provider=margin_provider,
        )
        results.append((name, backtest.run()))
    lines = [
        f"# XAUUSD M15 trend pullback, Version {version}: offline backtest",
        "",
        "Research only. No orders were placed; MT5 was used read-only for history and margin.",
        "",
        "## Status and assumptions",
        "",
        f"- Paper ledger: starts at £{config.starting_balance} for each period; 2% risk per trade.",
        f"- Cost scenario: {config.costs.label}.",
        *[f"- {note}" for note in cost_notes],
        "- **Not news-filtered:** no economic calendar source (Version 1.0 decision).",
        *(
            [
                "- **Real-yield filter (Version 1.1):** FRED DFII10 change over 20 published "
                "observations; <= -0.10 pp longs only, >= +0.10 pp shorts only, otherwise both. "
                "An observation is used from 17:00 New York on the next business day after its "
                "date. FRED's current vintage only (revisions cannot be checked).",
                "- **Out of sample is not blind:** the 2026 period was already viewed in the "
                "Version 1.0 reports before Version 1.1 was specified.",
            ]
            if config.real_yield_filter is not None
            else []
        ),
        "- Fills: longs buy at the ask (entry bar spread paid) and sell at the bid; shorts sell "
        "at the bid and buy back at the ask (exit bar spread paid). Stop exits slip by the "
        "evidenced stop percentile; take profits fill at the target; entries and market exits "
        "(forced close, trend exit) slip by the entry scenario. Stop assumed first when both "
        "are touched in one bar; gaps fill at the open. One spread value per bar, so intrabar "
        "spikes are not modelled.",
        "- Target: 2R from the quoted entry (Appendix A.F); the planned reward:risk at the "
        "actual fill is reported separately and is below 2 after entry slippage.",
        "- Forced close 16:45 New York; no entries 16:00-19:00 New York; no overnight positions.",
        "- Margin: MT5 `calc_margin` at the historical entry price, but with today's leverage "
        "and today's GBPUSD for the margin conversion.",
        "- Loss tick values use GBPUSD at each historical entry (MT5 provides no historical tick "
        "values).",
        "",
        "## Data coverage",
        "",
    ]
    for label, bars in (("XAUUSD M15", m15), ("XAUUSD H1", h1), ("GBPUSD M15", conversion_m15)):
        symbol, timeframe = label.split()
        c = coverage(symbol, timeframe, list(bars), calendar)
        lines.append(
            f"- {label}: {c.bars} bars, {c.first:%Y-%m-%d %H:%M} to {c.last:%Y-%m-%d %H:%M} UTC; "
            f"{len(c.gaps)} gaps during scheduled hours (holidays and early closes)"
        )
    lines += ["", "## Results", ""]
    for (name, start, end), (_, result) in zip(PERIODS, results, strict=True):
        window = f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"
        lines += [render_period(name, window, metrics(result))]
    lines += [
        "",
        f"Parameters were not optimised: the approved Version {version} values were used "
        "unchanged in every period.",
    ]
    return "\n".join(lines) + "\n", results


def decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def run_scenarios(
    *,
    scenarios: Sequence[tuple[str, BacktestConfig]],
    base: str,
    m15: Sequence[Bar],
    h1: Sequence[Bar],
    conversion_m15: Sequence[Bar],
    spec: InstrumentSpec,
    conversion_spec: InstrumentSpec,
    calendar: MarketCalendar,
    margin_provider: MarginProvider | None,
    cost_notes: Sequence[str],
    version: str = "1.0",
) -> tuple[str, dict[str, dict[str, Any]], list[tuple[str, BacktestResult]]]:
    """The base scenario in full, preceded by a summary of every scenario and period. Also
    returns every scenario's per-period metrics for the run manifest."""
    collected: dict[str, dict[str, Any]] = {}
    summary = [
        "## Cost scenarios",
        "",
        "Entry slippage is unknown, so every result depends on a labelled scenario. Stop-exit "
        "slippage uses percentiles of the account's observed stop-loss slippage.",
        "",
        "| Scenario | " + " | ".join(f"{name}: trades / net / PF" for name, _, _ in PERIODS) + " |",
        "|---|" + "---|" * len(PERIODS),
    ]
    base_text = ""
    base_results: list[tuple[str, BacktestResult]] = []
    for name, config in scenarios:
        text, results = run_periods(
            m15=m15,
            h1=h1,
            conversion_m15=conversion_m15,
            spec=spec,
            conversion_spec=conversion_spec,
            calendar=calendar,
            config=config,
            margin_provider=margin_provider,
            cost_notes=cost_notes,
            version=version,
        )
        cells = []
        collected[name] = {}
        for period, result in results:
            m = metrics(result)
            collected[name][period] = dataclasses.asdict(m)
            pf = "n/a" if m.profit_factor is None else f"{m.profit_factor:.2f}"
            cells.append(f"{m.trades} / £{m.net_gbp:,.2f} / {pf}")
        marker = " **(base)**" if name == base else ""
        summary.append(f"| {config.costs.label}{marker} | " + " | ".join(cells) + " |")
        if name == base:
            base_text, base_results = text, results
    head, _, rest = base_text.partition("## Data coverage")
    report = head + "\n".join(summary) + "\n\n## Data coverage" + rest
    return report, collected, base_results


def compare_versions(
    baseline: Sequence[tuple[str, BacktestResult]],
    filtered: Sequence[tuple[str, BacktestResult]],
    gate: RealYieldFilter,
) -> str:
    """Version 1.0 against Version 1.1 in the same cost scenario, with the Version 1.0 trades
    whose signal the real-yield rules reject. Removing a trade can free time for a different
    later trade, so the removed trades do not account exactly for the difference."""
    lines = [
        "## Version 1.0 against Version 1.1 (base scenario)",
        "",
        "| Period | Version | Trades | Win rate | Net (GBP) | Profit factor | Max drawdown |",
        "|---|---|---|---|---|---|---|",
    ]
    removed_lines = []
    for (name, before), (_, after) in zip(baseline, filtered, strict=True):
        for version, result in (("1.0", before), ("1.1", after)):
            m = metrics(result)
            pf = "n/a" if m.profit_factor is None else f"{m.profit_factor:.2f}"
            wr = "n/a" if m.win_rate is None else f"{m.win_rate:.1%}"
            lines.append(
                f"| {name} | {version} | {m.trades} | {wr} | £{m.net_gbp:,.2f} | {pf} | "
                f"{m.max_drawdown_percent:.1f}% |"
            )
        # The entry fills at the open of the bar after the signal bar, i.e. at the signal close.
        removed = [t for t in before.trades if gate.check(t.direction, t.entry_time) is not None]
        net = sum((t.net_gbp for t in removed), Decimal(0))
        wins = sum(1 for t in removed if t.net_gbp > 0)
        removed_lines.append(
            f"| {name} | {len(removed)} of {len(before.trades)} | {wins} | £{net:,.2f} |"
        )
    lines += [
        "",
        "Version 1.0 trades whose signal the Version 1.1 rules reject (their Version 1.0 result). "
        "Removing a trade can free time for a different later trade, so these do not account "
        "exactly for the difference between the versions.",
        "",
        "| Period | Removed | Of which wins | Net of removed (GBP) |",
        "|---|---|---|---|",
        *removed_lines,
    ]
    return "\n".join(lines) + "\n"
