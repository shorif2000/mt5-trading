"""Run the Version 1.0 backtest over the approved chronological periods and write a report."""

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

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
        *[f"- {note}" for note in cost_notes],
        "- **Not news-filtered:** no economic calendar source (Version 1.0 decision).",
        "- Fills: buys at the ask (bid open + bar spread), sells at the bid; stops and targets "
        "checked on the bid (longs) or ask (shorts); stop assumed first when both are touched in "
        "one bar; gaps fill at the open. Bar spread is one value per bar, so intrabar spread "
        "spikes are not modelled.",
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
