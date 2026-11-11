"""Record the Strategy A freeze for EXP-011: checksums of every frozen file and the fixed
volatility-tercile cut-offs. Refuses to overwrite an existing record (a new freeze would be a
new experiment).

    uv run python scripts/freeze_strategy_a.py

Cut-offs: terciles of the ADR ratio (ADR on the signal's trading day / median ADR of the
previous 60 trading days) over the 2023-2024 Strategy A signals of each arm; for the 0.10R
floor arm, only signals whose estimated cost (entry-bar spread + 7 + 40 points) is within
0.10 x the stop distance from the quoted entry.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

from trading.backtest.provenance import code_state
from trading.research.candidates import StrategyA
from trading.research.forward import FORWARD_START, FREEZE_RECORD, FROZEN_FILES, digest
from trading.research.inputs import load_inputs
from trading.research.levels import trading_day

POINT = Decimal("0.01")
FROM, TO = datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)


def tercile_cutoffs(values: list[float]) -> list[float]:
    v = sorted(values)
    return [v[len(v) // 3], v[2 * len(v) // 3]]


def main() -> None:
    if FREEZE_RECORD.exists():
        raise SystemExit(f"{FREEZE_RECORD} exists; the freeze is immutable")
    code = code_state()
    if code["dirty"]:
        raise SystemExit(f"commit first; uncommitted: {code['uncommitted_files']}")
    inp = load_inputs()
    a = StrategyA(inp.m15, inp.h1, inp.calendar, POINT)
    ratios: dict[str, list[float]] = {"no cost floor": [], "0.10R cost floor": []}
    for j, signal in a.signals.items():
        if not FROM <= inp.m15[j].open_time < TO or j + 1 >= len(inp.m15):
            continue
        ratio = a.levels.adr_ratio(trading_day(inp.m15[j].open_time))
        if ratio is None:
            continue
        ratios["no cost floor"].append(ratio)
        fill = inp.m15[j + 1]
        bid = Decimal(str(fill.open))
        entry = bid + fill.spread_points * POINT if signal.setup.direction.value == "buy" else bid
        risk = abs(entry - signal.setup.stop)
        if risk and (fill.spread_points + 47) * POINT <= Decimal("0.10") * risk:
            ratios["0.10R cost floor"].append(ratio)
    record = {
        "experiment": "EXP-011",
        "frozen_at": f"{datetime.now(UTC).isoformat(timespec='seconds')} on commit "
                     f"{code['short_commit']} ({code['branch']})",
        "forward_start_utc": FORWARD_START.isoformat(),
        "files": digest(FROZEN_FILES),
        "volatility_cutoffs": {arm: tercile_cutoffs(v) for arm, v in ratios.items()},
        "volatility_cutoff_signals": {arm: len(v) for arm, v in ratios.items()},
    }  # fmt: skip
    FREEZE_RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["volatility_cutoffs"]), record["volatility_cutoff_signals"])


if __name__ == "__main__":
    main()
