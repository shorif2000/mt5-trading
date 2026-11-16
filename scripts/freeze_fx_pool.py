"""Record the FX-pool freeze for EXP-014: checksums of every frozen file and, per instrument,
the fixed volatility-tercile cut-offs (same method as the XAUUSD freeze, scripts/
freeze_strategy_a.py, generalised: terciles of the ADR ratio over each instrument's own
2023-2024 Strategy A signals, since absolute ADR scales are not comparable across
instruments). Refuses to overwrite an existing record (a new freeze would be a new
experiment).

    uv run python scripts/freeze_fx_pool.py
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

from trading.backtest.provenance import code_state
from trading.research.fx_pool_forward import (
    FREEZE_RECORD,
    FROZEN_FILES,
    SPECS,
    FxPoolInputs,
    digest,
)
from trading.research.levels import trading_day
from trading.research.multi_market import GenericStrategyA

FROM, TO = datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
FORWARD_START_NOTE = "shared with EXP-011: 2026-11-15T23:00:00+00:00"


def tercile_cutoffs(values: list[float]) -> list[float]:
    v = sorted(values)
    return [v[len(v) // 3], v[2 * len(v) // 3]]


def main() -> None:
    if FREEZE_RECORD.exists():
        raise SystemExit(f"{FREEZE_RECORD} exists; the freeze is immutable")
    code = code_state()
    if code["dirty"]:
        raise SystemExit(f"commit first; uncommitted: {code['uncommitted_files']}")
    inp = FxPoolInputs()
    cutoffs: dict[str, dict[str, list[float]]] = {}
    signal_counts: dict[str, dict[str, int]] = {}
    for symbol in ("EURUSD", "GBPUSD", "USDJPY"):
        point = Decimal(str(SPECS[symbol].point))
        strategy = GenericStrategyA(inp.m15(symbol), inp.h1(symbol), inp.calendar, point, symbol)
        ratios: dict[str, list[float]] = {"no cost floor": [], "0.10R cost floor": []}
        for j, signal in strategy.signals.items():
            if not FROM <= strategy.m15[j].open_time < TO or j + 1 >= len(strategy.m15):
                continue
            ratio = strategy.levels.adr_ratio(trading_day(strategy.m15[j].open_time))
            if ratio is None:
                continue
            ratios["no cost floor"].append(ratio)
            fill = strategy.m15[j + 1]
            bid = Decimal(str(fill.open))
            buy = signal.setup.direction.value == "buy"
            entry = bid + fill.spread_points * point if buy else bid
            risk = abs(entry - signal.setup.stop)
            if risk and (fill.spread_points + 47) * point <= Decimal("0.10") * risk:
                ratios["0.10R cost floor"].append(ratio)
        cutoffs[symbol] = {arm: tercile_cutoffs(v) for arm, v in ratios.items()}
        signal_counts[symbol] = {arm: len(v) for arm, v in ratios.items()}
    record = {
        "experiment": "EXP-014",
        "frozen_at": f"{datetime.now(UTC).isoformat(timespec='seconds')} on commit "
                     f"{code['short_commit']} ({code['branch']})",
        "forward_start_utc": FORWARD_START_NOTE,
        "files": digest(FROZEN_FILES),
        "volatility_cutoffs": cutoffs,
        "volatility_cutoff_signals": signal_counts,
    }  # fmt: skip
    FREEZE_RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(cutoffs, indent=2))
    print(json.dumps(signal_counts))


if __name__ == "__main__":
    main()
