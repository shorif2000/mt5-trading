"""Backtest of the candidate strategies on the Version 1.0 engine (subclassed, not modified).

Reused unchanged from Version 1.0: entry fills (ask/bid at the next open plus the scenario's
entry slippage), the spread and 3 x ATR15 stop checks, the 2% risk engine, broker margin, exit
pricing (stop first within a bar, gaps at the open), costs, the 16:45 New York forced close,
no entries 16:00-19:00 and the GBP ledger.

Differences, all from the candidate specification and programme amendments:
- no H1 trend exit (the candidates define none);
- entry checks before the Version 1.0 ones, in this order: news (`NewsFilter`), the 0.10R
  cost floor (arm), and B's 1.2 reward:risk check against the midpoint target;
- B's target is the range midpoint (rounded towards the entry), A and C use 2R;
- B: after a stop-out at a boundary, signals at that exact boundary are blocked;
- signals while a position is open or pending are recorded ("position already open");
- ``fixed_risk``: sizing always uses the starting balance (2% of a constant £1,000).
"""

import dataclasses
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from trading.backtest.bars import Bar
from trading.backtest.engine import (
    Backtest,
    BacktestResult,
    Outcome,
    SignalRecord,
    TradeRecord,
    _Position,
)
from trading.models import Direction
from trading.research.candidates import Candidate
from trading.research.news import NewsFilter
from trading.strategies.xauusd_m15_pullback import Setup

M15 = timedelta(minutes=15)
FLOOR_ENTRY_POINTS, FLOOR_STOP_POINTS = Decimal(7), Decimal(40)  # base scenario (A1.3)


@dataclass(frozen=True)
class CandidateOptions:
    cost_floor: Decimal | None = None  # e.g. Decimal("0.10"): skip when C > 0.10 x stop
    news: NewsFilter | None = None
    fixed_risk: bool = False
    min_reward_risk: Decimal = Decimal("1.2")  # B only (targets from the strategy)


def _d(value: float) -> Decimal:
    return Decimal(str(value))


class CandidateBacktest(Backtest):
    def __init__(self, *, candidate: Candidate, options: CandidateOptions, **kwargs: Any) -> None:
        super().__init__(strategy=candidate, **kwargs)  # type: ignore[arg-type]
        self.candidate, self.options = candidate, options
        self.blocked: set[tuple[str, float]] = set()
        self.position_boundary: tuple[str, float] | None = None

    # --- entry ------------------------------------------------------------------------

    def _try_entry(
        self, setup: Setup, signal_time: Any, fill: Bar
    ) -> tuple[SignalRecord, _Position | None]:
        direction = setup.direction
        signal = self.candidate.signals[setup.signal_index]

        def filtered(reason: str) -> tuple[SignalRecord, None]:
            return SignalRecord(signal_time, direction, Outcome.FILTERED, (reason,)), None

        opts = self.options
        if opts.news is not None and (reason := opts.news.check(fill.open_time)):
            return filtered(reason)
        if signal.boundary is not None and signal.boundary in self.blocked:
            return filtered("boundary blocked after a stop-out")
        bid = _d(fill.open)
        ask = bid + fill.spread_points * self.point
        entry = ask if direction == Direction.BUY else bid
        risk = abs(entry - setup.stop)
        if opts.cost_floor is not None:
            cost = (fill.spread_points + FLOOR_ENTRY_POINTS + FLOOR_STOP_POINTS) * self.point
            if risk == 0 or cost > opts.cost_floor * risk:
                return filtered("estimated cost above 0.10R (cost floor)")
        target = None
        if signal.target_price is not None:
            rounding = ROUND_FLOOR if direction == Direction.BUY else ROUND_CEILING
            target = (_d(signal.target_price) / self.tick).to_integral_value(rounding) * self.tick
            reward = (target - entry) if direction == Direction.BUY else (entry - target)
            if risk == 0 or reward / risk < opts.min_reward_risk:
                return filtered("reward:risk to the range midpoint below 1.2")
        if opts.fixed_risk:
            self.balance = self.config.starting_balance
        record, position = super()._try_entry(setup, signal_time, fill)
        if position is not None:
            if target is not None:
                position.target = target
            self.position_boundary = signal.boundary
        return record, position

    def _close(self, position: _Position, bar: Bar, price: Decimal, reason: str,
               at: Any) -> TradeRecord | None:  # fmt: skip
        record = super()._close(position, bar, price, reason, at)
        if reason.startswith("stop") and self.position_boundary is not None:
            self.blocked.add(self.position_boundary)
        if self.options.fixed_risk:
            self.balance = self.config.starting_balance
        return record

    # --- run ----------------------------------------------------------------------------

    def run(self) -> BacktestResult:
        result = BacktestResult(starting_balance=self.balance)
        opts = self.options
        result.notes.append(
            "News filter: " + ("FOMC statements only (partial; CPI and payrolls not filtered)"
                               if opts.news is not None else "off"))  # fmt: skip
        position: _Position | None = None
        pending: tuple[Setup, Any] | None = None
        for index, bar in enumerate(self.m15):
            if pending is not None:
                setup, signal_time = pending
                pending = None
                if bar.open_time != signal_time:
                    record = SignalRecord(signal_time, setup.direction, Outcome.FILTERED,
                                          ("missing candle before entry",))  # fmt: skip
                else:
                    record, position = self._try_entry(setup, signal_time, bar)
                result.signals.append(self._with_event(record, setup))
            if position is not None:
                exit_at_open = None
                if bar.open_time >= position.force_close_at:
                    exit_at_open = "forced close 16:45 New York"
                if exit_at_open:
                    price = (_d(bar.open) if position.setup.direction == Direction.BUY
                             else _d(bar.open) + bar.spread_points * self.point)  # fmt: skip
                    hit: tuple[Decimal, str] | None = (price, exit_at_open)
                else:
                    hit = self._exit_level(position, bar)
                if hit is not None:
                    trade = self._close(position, bar, hit[0], hit[1], bar.open_time)
                    if trade is None:
                        result.notes.append(f"trade at {position.entry_time} without GBPUSD rate")
                    else:
                        result.trades.append(trade)
                    position = None
            close_time = bar.open_time + M15
            candidate_setup = self.candidate.evaluate(index)
            if candidate_setup is None:
                continue
            if (self.config.trade_from and close_time < self.config.trade_from) or (
                self.config.trade_until and close_time >= self.config.trade_until
            ):
                continue
            if position is not None or pending is not None:
                skipped = SignalRecord(close_time, candidate_setup.direction, Outcome.FILTERED,
                                       ("position already open",))  # fmt: skip
                result.signals.append(self._with_event(skipped, candidate_setup))
                continue
            reason = self._entry_time_problem(close_time)
            if reason is None and bar.spread_points > self.candidate.params.max_spread_points:
                reason = f"signal spread {bar.spread_points} points above maximum"
            if reason:
                filtered = SignalRecord(
                    close_time, candidate_setup.direction, Outcome.FILTERED, (reason,))
                result.signals.append(self._with_event(filtered, candidate_setup))
            else:
                pending = (candidate_setup, close_time)
        if position is not None:
            last = self.m15[-1]
            price = (_d(last.close) if position.setup.direction == Direction.BUY
                     else _d(last.close) + last.spread_points * self.point)  # fmt: skip
            trade = self._close(position, last, price, "end of data", last.open_time + M15)
            if trade is not None:
                result.trades.append(trade)
        result.final_balance = self.balance
        return result


def with_period(config: Any, start: Any, end: Any) -> Any:
    return dataclasses.replace(config, trade_from=start, trade_until=end)
