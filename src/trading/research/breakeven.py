"""EXP-001: break-even stop management replayed on the fixed Version 1.0 entry list.

Only the stop changes. Entries, fills, volumes, the initial stop, the target, the 16:45 New
York forced close and the H1 trend exit are Version 1.0's, and every exit is priced and costed
by the Version 1.0 engine itself (`Backtest._exit_level` and `Backtest._close`), so the
control variant reproduces Version 1.0 trade for trade.

Primary method (programme Amendment 1, A1.2): **bar-close management**. After an M15 bar of an
open trade closes, if the favourable excursion since entry (bid for longs, ask for shorts) has
reached the trigger, the break-even stop is active from the next bar's open. The original stop
and target stay in force throughout the trigger bar.

Sensitivity only (never mixed into the primary results): **intrabar management**, where the
stop moves the moment the trigger is touched. On M15 this is ambiguous when the trigger bar also
touches the new stop, so it is run under both orderings, or resolved from ticks where a
``TickResolver`` can decide a bar.
"""

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from trading.backtest.bars import Bar
from trading.backtest.engine import Backtest, TradeRecord, _Position
from trading.models import Direction

M15 = timedelta(minutes=15)


@dataclass(frozen=True)
class BreakEvenRule:
    name: str
    trigger_r: Decimal | None  # None: never move the stop (control)
    plus_costs: bool = False  # stop to entry fill plus estimated round-trip cost


VARIANTS = (
    BreakEvenRule("BE-0 (control)", None),
    BreakEvenRule("BE-0.5", Decimal("0.5")),
    BreakEvenRule("BE-0.75", Decimal("0.75")),
    BreakEvenRule("BE-1.0", Decimal("1.0")),
    BreakEvenRule("BE-1.0+C", Decimal("1.0"), plus_costs=True),
)


class Mode(StrEnum):
    BAR_CLOSE = "bar-close (primary)"
    INTRABAR_EXIT_FIRST = "intrabar: trigger then break-even exit in the trigger bar"
    INTRABAR_NO_EXIT = "intrabar: no break-even exit in the trigger bar"
    INTRABAR_TICKS = "intrabar: trigger bar resolved from ticks"


class TickOutcome(StrEnum):
    """What happened first inside a trigger bar, from ticks."""

    ORIGINAL_STOP = "original stop"
    TARGET = "target"
    BREAK_EVEN = "break-even exit"
    TRIGGER_ONLY = "trigger, no exit in the bar"
    NO_TRIGGER = "no trigger in the bar"


# (bar, direction, entry fill, original stop, target, trigger price, break-even level) ->
# outcome, or None when ticks do not cover the bar.
TickResolver = Callable[[Bar, Direction, Decimal, Decimal, Decimal, Decimal, Decimal],
                        TickOutcome | None]  # fmt: skip


@dataclass(frozen=True)
class ReplayedTrade:
    record: TradeRecord  # exit priced by the Version 1.0 engine; ``stop`` is the initial stop
    rule: str
    initial_stop: Decimal
    break_even_level: Decimal | None
    moved_at: datetime | None  # when the break-even stop became active
    break_even_exit: bool
    ambiguous_trigger_bar: bool  # trigger bar also touched the break-even level
    tick_resolved: bool | None  # INTRABAR_TICKS only: True resolved, False not covered
    later_reached_target: bool | None  # break-even exits only: original target hit after
    event: tuple[str, datetime] | None


def _d(value: float) -> Decimal:
    return Decimal(str(value))


class BreakEvenReplay:
    """Replays Version 1.0 trades through a Version 1.0 `Backtest` configured with one cost
    scenario. The engine object is used only for pricing, costs and the GBP ledger."""

    def __init__(self, engine: Backtest) -> None:
        self.engine = engine
        self.index = {bar.open_time: i for i, bar in enumerate(engine.m15)}
        self.point = engine.point

    # --- prices -------------------------------------------------------------------------

    def _excursion(self, direction: Direction, fill: Decimal, bar: Bar) -> Decimal:
        """Best executable exit price move in the trade's favour within ``bar``."""
        if direction == Direction.BUY:
            return _d(bar.high) - fill
        return fill - (_d(bar.low) + bar.spread_points * self.point)

    def _touches_level(self, direction: Direction, level: Decimal, bar: Bar) -> bool:
        if direction == Direction.BUY:
            return _d(bar.low) <= level
        return _d(bar.high) + bar.spread_points * self.point >= level

    def _market_price(self, direction: Direction, bar: Bar) -> Decimal:
        """Executable price at the bar open: the bid for a long, the ask for a short."""
        if direction == Direction.BUY:
            return _d(bar.open)
        return _d(bar.open) + bar.spread_points * self.point

    # --- replay -------------------------------------------------------------------------

    def position_for(self, trade: TradeRecord, entry_spread_points: int) -> _Position:
        """The Version 1.0 position as it stood at entry, with this scenario's entry fill."""
        engine = self.engine
        setup = engine.strategy.evaluate(self.index[trade.entry_time - M15])
        if setup is None or setup.stop != trade.stop or setup.direction != trade.direction:
            raise ValueError(f"Version 1.0 setup not reproduced for {trade.entry_time}")
        spread = entry_spread_points * self.point
        quoted = trade.quoted_entry
        buy = trade.direction == Direction.BUY
        return _Position(
            setup=setup,
            entry_time=trade.entry_time,
            quoted_entry=quoted,
            entry_bid=quoted - spread if buy else quoted,
            entry_spread=spread,
            entry_price=quoted + engine.entry_slippage if buy else quoted - engine.entry_slippage,
            target=trade.target,
            volume=trade.volume,
            force_close_at=engine._force_close_for(trade.entry_time),
            maximum_risk=trade.maximum_risk,
            estimated_loss=trade.estimated_loss,
        )

    def break_even_level(self, rule: BreakEvenRule, position: _Position) -> Decimal:
        level = position.entry_price
        if not rule.plus_costs:
            return level
        costs = self.engine.costs
        cost = position.entry_spread + (costs.entry_points + costs.stop_exit_points) * self.point
        return level + cost if position.setup.direction == Direction.BUY else level - cost

    def replay(
        self,
        trade: TradeRecord,
        rule: BreakEvenRule,
        mode: Mode = Mode.BAR_CLOSE,
        tick_resolver: TickResolver | None = None,
    ) -> ReplayedTrade | None:
        """Replay one trade. None when the engine has no GBPUSD rate at the exit (as V1.0)."""
        engine = self.engine
        start = self.index[trade.entry_time]
        position = self.position_for(trade, engine.m15[start].spread_points)
        direction = position.setup.direction
        initial_stop = position.setup.stop
        r_distance = abs(position.quoted_entry - initial_stop)
        trigger = None if rule.trigger_r is None else rule.trigger_r * r_distance
        level = self.break_even_level(rule, position) if trigger is not None else None
        best = Decimal("-Infinity")
        pending = moved_at = None
        ambiguous = False
        tick_resolved: bool | None = None
        intrabar = mode != Mode.BAR_CLOSE
        exit_: tuple[Bar, Decimal, str] | None = None
        for bar in engine.m15[start:]:
            if pending is not None:  # activation at this bar's open
                position.setup = dataclasses.replace(position.setup, stop=pending)
                moved_at, pending = bar.open_time, None
            hit = self._exit_at_open(position, bar)
            outcome = None
            if hit is None and intrabar and level is not None and moved_at is None:
                assert trigger is not None
                outcome = self._intrabar_trigger_bar(
                    position, bar, trigger, level, mode, tick_resolver)  # fmt: skip
            if outcome is not None:
                hit, activated, amb, resolved = outcome
                ambiguous = ambiguous or amb
                tick_resolved = resolved if resolved is not None else tick_resolved
                if activated and (hit is None or hit[1] == "stop (break-even)"):
                    assert level is not None
                    position.setup = dataclasses.replace(position.setup, stop=level)
                    moved_at = bar.open_time
            elif hit is None:
                hit = engine._exit_level(position, bar)
            if hit is not None:
                price, reason = hit
                moved_stop_hit = moved_at is not None and reason.startswith("stop")
                if moved_stop_hit and "break-even" not in reason:
                    reason = "stop (break-even gap)" if "gap" in reason else "stop (break-even)"
                exit_ = (bar, price, reason)
                break
            close_time = bar.open_time + M15
            if close_time.minute == 0 and engine.strategy.trend_at(close_time) != direction:
                position.exit_next_open = "H1 trend invalidated"
            if level is not None and trigger is not None and moved_at is None and not intrabar:
                best = max(best, self._excursion(direction, position.entry_price, bar))
                if best >= trigger:
                    pending = level
                    ambiguous = ambiguous or self._touches_level(direction, level, bar)
        # The exit price is decided; `_close` reads the stop only for the record and the planned
        # reward:risk, which refer to the initial stop (and would divide by zero at break-even).
        position.setup = dataclasses.replace(position.setup, stop=initial_stop)
        if exit_ is None:  # end of data, as Version 1.0
            last = engine.m15[-1]
            price = _d(last.close) if direction == Direction.BUY else (
                _d(last.close) + last.spread_points * self.point)  # fmt: skip
            record = engine._close(position, last, price, "end of data", last.open_time + M15)
        else:
            bar, price, reason = exit_
            record = engine._close(position, bar, price, reason, bar.open_time)
        if record is None:
            return None
        be_exit = "break-even" in record.exit_reason
        later = self._later_reached_target(trade, record, initial_stop) if be_exit else None
        event = None
        if position.setup.pullback_event_start >= 0:
            event = (direction.value, engine.m15[position.setup.pullback_event_start].open_time)
        return ReplayedTrade(record, rule.name, initial_stop, level, moved_at, be_exit,
                             ambiguous, tick_resolved, later, event)  # fmt: skip

    def _exit_at_open(self, position: _Position, bar: Bar) -> tuple[Decimal, str] | None:
        """Version 1.0 market exits at the open: forced close, then a flagged trend exit."""
        reason = None
        if bar.open_time >= position.force_close_at:
            reason = "forced close 16:45 New York"
        elif position.exit_next_open:
            reason = position.exit_next_open
        if reason is None:
            return None
        return self._market_price(position.setup.direction, bar), reason

    def _intrabar_trigger_bar(
        self,
        position: _Position,
        bar: Bar,
        trigger: Decimal,
        level: Decimal,
        mode: Mode,
        tick_resolver: TickResolver | None,
    ) -> tuple[tuple[Decimal, str] | None, bool, bool, bool | None] | None:
        """Intrabar management in a bar where the stop has not moved yet. Returns (exit,
        activated, ambiguous, tick_resolved), or None when the trigger is not reached so the
        bar is handled by the normal Version 1.0 rule."""
        engine = self.engine
        direction = position.setup.direction
        original = engine._exit_level(position, bar)
        if original is not None and "gap" in original[1]:
            return original, False, False, None  # gaps at the open come before any trigger
        if self._excursion(direction, position.entry_price, bar) < trigger:
            return None
        stop_touched = original is not None and original[1] == "stop"
        target_touched = self._touches_target(position, bar)
        be_touched = self._touches_level(direction, level, bar)
        ambiguous = stop_touched or be_touched
        if mode == Mode.INTRABAR_TICKS and ambiguous:
            if tick_resolver is None:
                raise ValueError("tick mode needs a tick resolver")
            buy = direction == Direction.BUY
            fill = position.entry_price
            trigger_price = fill + trigger if buy else fill - trigger
            outcome = tick_resolver(bar, direction, position.entry_price, position.setup.stop,
                                    position.target, trigger_price, level)  # fmt: skip
            if outcome is not None:
                return self._from_tick_outcome(outcome, position, level) + (True,)
            mode = Mode.INTRABAR_EXIT_FIRST  # not covered by ticks: fall back, flagged
            resolved: bool | None = False
        else:
            resolved = None
        if stop_touched:  # Version 1.0 convention: the original stop first
            return original, False, ambiguous, resolved
        if be_touched and mode != Mode.INTRABAR_NO_EXIT:
            return (level, "stop (break-even)"), True, ambiguous, resolved
        if target_touched:
            return (position.target, "target"), True, ambiguous, resolved
        return None, True, ambiguous, resolved

    def _from_tick_outcome(
        self, outcome: TickOutcome, position: _Position, level: Decimal
    ) -> tuple[tuple[Decimal, str] | None, bool, bool]:
        if outcome == TickOutcome.ORIGINAL_STOP:
            return (position.setup.stop, "stop"), False, True
        if outcome == TickOutcome.TARGET:
            return (position.target, "target"), True, True
        if outcome == TickOutcome.BREAK_EVEN:
            return (level, "stop (break-even)"), True, True
        if outcome == TickOutcome.TRIGGER_ONLY:
            return None, True, True
        return None, False, True

    def _touches_target(self, position: _Position, bar: Bar) -> bool:
        if position.setup.direction == Direction.BUY:
            return _d(bar.high) >= position.target
        return _d(bar.low) + bar.spread_points * self.point <= position.target

    def _later_reached_target(
        self, trade: TradeRecord, record: TradeRecord, initial_stop: Decimal
    ) -> bool:
        """After a break-even exit, would the original stop and target have reached the target
        first? Replayed with Version 1.0 rules from the exit bar (stop first in a bar)."""
        engine = self.engine
        start = self.index[trade.entry_time]
        position = self.position_for(trade, engine.m15[start].spread_points)
        position.setup = dataclasses.replace(position.setup, stop=initial_stop)
        exit_index = self.index.get(record.exit_time, len(engine.m15))
        for i, bar in enumerate(engine.m15[start:], start=start):
            if i >= exit_index:
                if self._exit_at_open(position, bar) is not None:
                    return False
                hit = engine._exit_level(position, bar)
                if hit is not None:
                    return hit[1].startswith("target")
            close_time = bar.open_time + M15
            if close_time.minute == 0 and engine.strategy.trend_at(close_time) != (
                position.setup.direction
            ):
                position.exit_next_open = "H1 trend invalidated"
        return False


def trade_from_manifest(row: dict[str, Any]) -> TradeRecord:
    """A Version 1.0 trade as stored in a run manifest."""

    def dec(key: str) -> Decimal:
        return Decimal(row[key])

    def opt(key: str) -> Decimal | None:
        return None if row.get(key) is None else Decimal(row[key])

    return TradeRecord(
        direction=Direction(row["direction"]),
        entry_time=datetime.fromisoformat(row["entry_time"]),
        exit_time=datetime.fromisoformat(row["exit_time"]),
        quoted_entry=dec("quoted_entry"),
        entry_price=dec("entry_price"),
        exit_price=dec("exit_price"),
        stop=dec("stop"),
        target=dec("target"),
        volume=dec("volume"),
        exit_reason=row["exit_reason"],
        exit_kind=row["exit_kind"],
        gross_gbp=dec("gross_gbp"),
        spread_cost_gbp=dec("spread_cost_gbp"),
        entry_slippage_gbp=dec("entry_slippage_gbp"),
        exit_slippage_gbp=dec("exit_slippage_gbp"),
        commission_gbp=dec("commission_gbp"),
        net_gbp=dec("net_gbp"),
        planned_reward_to_risk=dec("planned_reward_to_risk"),
        realised_r=opt("realised_r"),
        balance_after=dec("balance_after"),
        maximum_risk=opt("maximum_risk"),
        estimated_loss=opt("estimated_loss"),
    )


def replay_period(
    replay: BreakEvenReplay,
    trades: Sequence[TradeRecord],
    rule: BreakEvenRule,
    mode: Mode = Mode.BAR_CLOSE,
    tick_resolver: TickResolver | None = None,
) -> list[ReplayedTrade]:
    """Replay a period's trades in order on one compounding ledger (the engine's balance)."""
    out = []
    for trade in trades:
        result = replay.replay(trade, rule, mode, tick_resolver)
        if result is not None:
            out.append(result)
    return out


@dataclass(frozen=True)
class Tick:
    time: datetime  # aware UTC
    bid: Decimal
    ask: Decimal


def resolve_from_ticks(
    ticks: Sequence[Tick],
    bar: Bar,
    direction: Direction,
    stop: Decimal,
    target: Decimal,
    trigger_price: Decimal,
    level: Decimal,
    coverage_tolerance: timedelta = timedelta(seconds=60),
) -> TickOutcome | None:
    """First decisive event inside ``bar`` from its ticks, or None when the ticks do not cover
    the whole bar. Longs are tested on the bid, shorts on the ask (their exit side)."""
    end = bar.open_time + M15
    inside = [t for t in ticks if bar.open_time <= t.time < end]
    if (not inside or inside[0].time - bar.open_time > coverage_tolerance
            or end - inside[-1].time > coverage_tolerance):  # fmt: skip
        return None
    buy = direction == Direction.BUY

    def reached(price: Decimal, level_: Decimal) -> bool:  # in the trade's favour
        return price >= level_ if buy else price <= level_

    def fell_to(price: Decimal, level_: Decimal) -> bool:  # against the trade
        return price <= level_ if buy else price >= level_

    triggered = False
    for tick in inside:
        price = tick.bid if buy else tick.ask
        if reached(price, target):
            return TickOutcome.TARGET
        if not triggered:
            if fell_to(price, stop):
                return TickOutcome.ORIGINAL_STOP
            triggered = reached(price, trigger_price)
        elif fell_to(price, level):
            return TickOutcome.BREAK_EVEN
    return TickOutcome.TRIGGER_ONLY if triggered else TickOutcome.NO_TRIGGER
