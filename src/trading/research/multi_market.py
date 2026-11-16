"""Generic multi-instrument variant of the frozen Strategy A pipeline, for forward evidence on
EURUSD, GBPUSD and USDJPY pooled alongside EXP-011's XAUUSD stream (EXP-013/014).

Imports the frozen `engine.py`/`levels.py`/`candidates.py`/`candidate_engine.py` unchanged and
reuses them wherever their logic is already symbol-agnostic (indicator maths, exit pricing in
`Backtest._exit_level`/`_close`, the news filter, the cost-floor check, `_usd_to_gbp_rate`'s
conversion arithmetic). Overrides only what those modules hardcode to the literal "XAUUSD" or
"GBPUSD" as module constants, never by editing them:

- `Levels.complete()` checks the calendar under the literal "XAUUSD"; `GenericLevels` takes an
  explicit ``symbol`` instead, reusing the real per-symbol session config already present in
  `config/market_sessions.yaml` ("forex": EURUSD, GBPUSD, USDJPY; "gold": XAUUSD).
- `Backtest.__init__`/`_try_entry` build a `SizingRequest` and a `parse_margin_response` call
  tagged "XAUUSD" regardless of what is actually traded. `parse_margin_response` validates
  that tag against the broker's own "symbol" field in the margin response
  (`src/trading/risk/margin.py`), so reusing it unmodified would reject every real margin
  response for a non-gold instrument, not just mislabel it. `_snapshot`'s `Quote` tags are the
  same mistake, cosmetic but corrected for consistency.
- `_usd_to_gbp_rate`'s arithmetic is already generic: it returns "GBP per 1 unit of the
  conversion pair's quote currency" from whatever GBP-base pair is supplied as
  `conversion_m15`/`conversion_spec", so it is inherited unchanged. GBPUSD converts USD-quoted
  pairs (EURUSD, and GBPUSD itself, self-converting); GBPJPY converts USDJPY's JPY-quoted P&L.
  Neither needs a composed two-leg cross.
- Gold's forced close and no-entry window (Version 1.0 Amendment 1) were built for gold's own
  17:00-18:00 New York daily break. EURUSD/GBPUSD/USDJPY trade continuously under the "forex"
  session profile, with no such break to anchor an equivalent rule to. Owner decision
  2026-11-16 (programme Amendment 6): for these three instruments only, drop the forced close
  and the no-entry window entirely; a position runs until its stop or the 2R target. XAUUSD
  (EXP-011) is completely unaffected either way, and is never touched by this module.
"""

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from trading.backtest.bars import Bar
from trading.backtest.engine import (
    BacktestConfig,
    MarginProvider,
    Outcome,
    SignalRecord,
    _d,
    _Position,
)
from trading.market_data.sessions import MarketCalendar
from trading.models import AccountSnapshot, Direction, InstrumentSpec, MarketSnapshot, Quote
from trading.research.candidate_engine import (
    FLOOR_ENTRY_POINTS,
    FLOOR_STOP_POINTS,
    CandidateBacktest,
    CandidateOptions,
)
from trading.research.candidates import (
    Candidate,
    CandidateParams,
    CandidateSignal,
    EventLog,
    StrategyA,
)
from trading.research.levels import Levels
from trading.risk.margin import (
    MarginAccount,
    MarginUnavailable,
    Side,
    check_margin,
    parse_margin_response,
)
from trading.risk.position_sizing import SizingRequest, size_position
from trading.strategies.xauusd_m15_pullback import Setup, target_price

M15 = timedelta(minutes=15)
NEVER = datetime(2099, 1, 1, tzinfo=UTC)  # sentinel: the forced-close check never fires for FX


class GenericLevels(Levels):
    """`Levels` for any symbol, not just XAUUSD."""

    def __init__(self, m15: Sequence[Bar], calendar: MarketCalendar, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(m15, calendar)

    def complete(self, first: int, last: int, step: timedelta = M15) -> bool:
        for previous, current in zip(self.m15[first:last], self.m15[first + 1 : last + 1],
                                     strict=False):  # fmt: skip
            missing = self.calendar.open_time(self.symbol, previous.open_time + step,
                                              current.open_time)  # fmt: skip
            if missing > self.calendar.max_unexplained_gap:
                return False
        return True


class GenericStrategyA(StrategyA):
    """Strategy A for any symbol. `StrategyA.scan()` itself never references a hardcoded
    symbol (checked: only `StrategyB._h1_complete` does, and B is not used here); only the
    `Levels` it scans against needs to know the real symbol."""

    def __init__(self, m15: Sequence[Bar], h1: Sequence[Bar], calendar: MarketCalendar,
                 tick: Decimal, symbol: str) -> None:  # fmt: skip
        self.m15, self.h1, self.tick = m15, h1, tick
        self.params = CandidateParams()
        self.levels = GenericLevels(m15, calendar, symbol)
        self.atr15 = self.levels.atr15
        self.signals: dict[int, CandidateSignal] = {}
        self.events: list[EventLog] = []
        self.scan()


class GenericCandidateBacktest(CandidateBacktest):
    """`CandidateBacktest` for any instrument. `__init__` never calls `super().__init__()`:
    that chain (`CandidateBacktest.__init__` -> `Backtest.__init__`) bakes the commission
    lookup and the sizing-allowance key to the module constant "XAUUSD", so it is
    reimplemented here directly with the real symbol instead. Every attribute the inherited
    methods need is set directly below, so `_exit_level`, `_close` and `run()` (all inherited,
    unmodified, from `Backtest`/`CandidateBacktest`, and none of them reference a hardcoded
    symbol) work correctly through ordinary Python method dispatch.
    """

    def __init__(
        self,
        *,
        candidate: Candidate,
        options: CandidateOptions,
        symbol: str,
        conversion_symbol: str,
        m15: Sequence[Bar],
        h1: Sequence[Bar],
        conversion_m15: Sequence[Bar],
        spec: InstrumentSpec,
        conversion_spec: InstrumentSpec,
        calendar: MarketCalendar,
        config: BacktestConfig,
        margin_provider: MarginProvider | None,
    ) -> None:
        self.symbol, self.conversion_symbol = symbol, conversion_symbol
        self.m15, self.h1, self.spec, self.calendar, self.config = m15, h1, spec, calendar, config
        self.conversion_spec = conversion_spec
        self.conversion = {bar.open_time: bar for bar in conversion_m15}
        self.margin_provider = margin_provider
        self.point = _d(spec.point or spec.tick_size)
        self.tick = _d(spec.tick_size)
        self.contract = _d(spec.contract_size)
        self.zone = ZoneInfo(config.sessions.zone)
        self.strategy = candidate  # type: ignore[assignment]
        commission = config.sizing.commission_per_lot.get(symbol)
        if commission is None:
            raise ValueError(f"{symbol} commission must be configured before a backtest")
        self.commission = commission
        self.costs = config.costs
        self.entry_slippage = config.costs.entry_points * self.point
        allowance = config.costs.sizing_allowance()
        self.sizing = dataclasses.replace(
            config.sizing,
            slippage_points={**config.sizing.slippage_points, symbol: allowance},
        )
        self.balance = config.starting_balance
        self.candidate, self.options = candidate, options
        self.blocked: set[tuple[str, float]] = set()
        self.position_boundary: tuple[str, float] | None = None

    # --- symbol-dependent overrides (the only reason this class exists) -------------------

    def _force_close_for(self, entry: datetime) -> datetime:
        return NEVER  # no gold-style daily break on a continuously-traded FX pair

    def _entry_time_problem(self, moment: datetime) -> str | None:
        if self.calendar.open_time(self.symbol, moment, moment + M15) < M15:
            return "outside the verified trading session"
        if any(n.startswith("unconfirmed")
               for n in self.calendar.notes(self.symbol, moment, moment + M15)):  # fmt: skip
            return "date has an unconfirmed broker holiday schedule"
        return None

    def _window_is_complete(self, first: int, last: int) -> bool:
        for previous, current in zip(self.m15[first:last], self.m15[first + 1 : last + 1],
                                     strict=False):  # fmt: skip
            missing = self.calendar.open_time(self.symbol, previous.open_time + M15,
                                              current.open_time)  # fmt: skip
            if missing > self.calendar.max_unexplained_gap:
                return False
        return True

    def _snapshot(self, fill: Bar, rate: Decimal) -> MarketSnapshot | None:
        conversion = self.conversion.get(fill.open_time)
        if conversion is None:
            return None
        bid = _d(fill.open)
        ask = bid + fill.spread_points * self.point
        tick_value = float(self.contract * self.tick * rate)
        spec = self.spec.model_copy(update={
            "tick_value": tick_value, "tick_value_loss": tick_value,
            "tick_value_profit": tick_value})  # fmt: skip
        c_point = _d(self.conversion_spec.point or 0.00001)
        quotes = [
            Quote(
                symbol=self.symbol,
                bid=float(bid),
                ask=float(ask),
                timestamp=fill.open_time,
                point=float(self.point),
                digits=self.spec.digits or 2,
            ),  # fmt: skip
            Quote(
                symbol=self.conversion_symbol,
                bid=conversion.open,
                ask=float(_d(conversion.open) + conversion.spread_points * c_point),
                timestamp=fill.open_time,
                point=float(c_point),
                digits=self.conversion_spec.digits or 5,
            ),  # fmt: skip
        ]
        balance = float(self.balance)
        account = AccountSnapshot(
            login="PAPER", server="paper", currency=self.config.account_currency,
            balance=balance, credit=0, equity=balance, margin=0, free_margin=balance,
            timestamp=fill.open_time, stop_out_mode=self.config.stop_out_mode,
            margin_call_level=float(self.config.margin_call_level))  # fmt: skip
        return MarketSnapshot(account=account, quotes=quotes,
                              instruments=[spec, self.conversion_spec],
                              generated_at=fill.open_time)  # fmt: skip

    def _enter(self, setup: Setup, signal_time: Any, fill: Bar
              ) -> tuple[SignalRecord, _Position | None]:  # fmt: skip
        """`Backtest._try_entry`'s body, with ``self.symbol`` instead of the module SYMBOL."""
        direction = setup.direction

        def record(outcome: Outcome, *reasons: str, **extra: Any) -> tuple[SignalRecord, None]:
            return SignalRecord(signal_time, direction, outcome, reasons, **extra), None

        p = self.strategy.params
        if fill.spread_points > p.max_spread_points:
            return record(Outcome.FILTERED,
                          f"entry spread {fill.spread_points} points above maximum")  # fmt: skip
        bid = _d(fill.open)
        ask = bid + fill.spread_points * self.point
        entry = ask if direction == Direction.BUY else bid
        if abs(entry - setup.stop) > _d(p.max_stop_atr) * _d(setup.atr):
            return record(Outcome.FILTERED, "stop wider than 3 x ATR(14)")
        rate = self._usd_to_gbp_rate(fill.open_time)
        snapshot = self._snapshot(fill, rate) if rate is not None else None
        if snapshot is None or rate is None:
            reason = f"{self.conversion_symbol} quote unavailable for currency conversion"
            return record(Outcome.RISK_REJECTED, reason)
        request = SizingRequest(self.symbol, "buy" if direction == Direction.BUY else "sell",
                                entry, setup.stop, "executable", holding_nights=0)  # fmt: skip
        sizing = size_position(snapshot, request, self.sizing, now=fill.open_time)
        if not sizing.accepted or sizing.volume is None:
            minimum = (sizing.estimated_loss
                       if any(r.startswith("minimum volume") for r in sizing.reasons)
                       else None)  # fmt: skip
            return record(Outcome.RISK_REJECTED, *sizing.reasons,
                          maximum_risk=sizing.maximum_risk,
                          minimum_volume_loss=minimum)  # fmt: skip
        side: Side = "BUY" if direction == Direction.BUY else "SELL"
        if self.margin_provider is None:
            return record(Outcome.MARGIN_REJECTED, "broker margin unavailable (no margin source)",
                          volume=sizing.volume, estimated_loss=sizing.estimated_loss)  # fmt: skip
        try:
            response = self.margin_provider(side, sizing.volume, entry)
            estimate = parse_margin_response(response, symbol=self.symbol, side=side,
                                             volume=sizing.volume)  # fmt: skip
        except MarginUnavailable as exc:
            return record(Outcome.MARGIN_REJECTED, str(exc), volume=sizing.volume,
                          estimated_loss=sizing.estimated_loss)  # fmt: skip
        account = MarginAccount(self.config.account_currency, self.balance, Decimal(0),
                                self.balance, self.config.stop_out_mode,
                                self.config.margin_call_level)  # fmt: skip
        margin = check_margin(account, estimate)
        if not margin.accepted:
            return record(Outcome.MARGIN_REJECTED, *margin.reasons, volume=sizing.volume,
                          estimated_loss=sizing.estimated_loss,
                          required_margin=margin.required)  # fmt: skip
        slip = self.entry_slippage if direction == Direction.BUY else -self.entry_slippage
        position = _Position(
            setup=setup, entry_time=fill.open_time, quoted_entry=entry, entry_bid=bid,
            entry_spread=ask - bid, entry_price=entry + slip,
            target=target_price(entry, setup.stop, p.target_r, self.tick), volume=sizing.volume,
            force_close_at=self._force_close_for(fill.open_time),
            maximum_risk=sizing.maximum_risk, estimated_loss=sizing.estimated_loss)  # fmt: skip
        signal = SignalRecord(signal_time, direction, Outcome.EXECUTABLE, sizing.reasons,
                              volume=sizing.volume, estimated_loss=sizing.estimated_loss,
                              maximum_risk=sizing.maximum_risk,
                              required_margin=margin.required)  # fmt: skip
        return signal, position

    def _try_entry(self, setup: Setup, signal_time: Any, fill: Bar
                   ) -> tuple[SignalRecord, _Position | None]:  # fmt: skip
        """`CandidateBacktest._try_entry`'s pre-checks (news, cost floor, B's reward:risk),
        calling `_enter` above instead of `Backtest._try_entry`."""
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
        record, position = self._enter(setup, signal_time, fill)
        if position is not None:
            if target is not None:
                position.target = target
            self.position_boundary = signal.boundary
        return record, position
