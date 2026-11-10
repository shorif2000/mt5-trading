"""Run the Version 1.0 backtest over the approved chronological periods and write a report."""

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading.backtest.bars import Bar
from trading.backtest.engine import Backtest, BacktestConfig, BacktestResult, MarginProvider
from trading.backtest.history_bars import coverage
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
        "# XAUUSD M15 trend pullback, Version 1.0: offline backtest",
        "",
        "Research only. No orders were placed; MT5 was used read-only for history and margin.",
        "",
        "## Status and assumptions",
        "",
        f"- Paper ledger: starts at £{config.starting_balance} for each period; 2% risk per trade.",
        f"- Cost scenario: {config.costs.label}.",
        *[f"- {note}" for note in cost_notes],
        "- **Not news-filtered:** no economic calendar source (Version 1.0 decision).",
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
        "Parameters were not optimised: the approved Version 1.0 values were used unchanged in "
        "every period.",
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
) -> tuple[str, dict[str, dict[str, Any]]]:
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
            base_text = text
    head, _, rest = base_text.partition("## Data coverage")
    return head + "\n".join(summary) + "\n\n## Data coverage" + rest, collected
